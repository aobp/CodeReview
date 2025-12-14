"""Main entry point for the AI Code Review Agent.

This script demonstrates the complete workflow:
1. Initialize Storage (DAO layer)
2. Build Assets (RepoMap) if needed
3. Initialize Autonomous ReAct Agent
4. Run the agent workflow
5. Display review results
"""

import asyncio
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from core.config import Config
from dao.factory import get_storage
from assets.implementations.repo_map import RepoMapBuilder
from agents.bot import run_react_agent


def load_diff_from_file(file_path: Path) -> str:
    """Load Git diff from a file.
    
    Args:
        file_path: Path to the diff file.
    
    Returns:
        The diff content as a string.
    
    Raises:
        FileNotFoundError: If the file doesn't exist.
        IOError: If the file cannot be read.
    """
    file_path = Path(file_path).resolve()
    
    if not file_path.exists():
        raise FileNotFoundError(f"Diff file not found: {file_path}")
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise IOError(f"Error reading diff file: {e}")


def get_git_info(repo_path: Path, ref: str = "HEAD") -> Tuple[Optional[str], Optional[str]]:
    """Get Git branch and commit hash for a repository.
    
    Args:
        repo_path: Path to the Git repository.
        ref: Git reference (branch, tag, or commit). Default: "HEAD".
    
    Returns:
        A tuple of (branch_name, commit_hash). Returns (None, None) if not a Git repo or error.
    """
    repo_path = Path(repo_path).resolve()
    
    try:
        # Get current branch name
        branch_result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", ref],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8"
        )
        branch = branch_result.stdout.strip()
        
        # Get commit hash
        commit_result = subprocess.run(
            ["git", "rev-parse", ref],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8"
        )
        commit_hash = commit_result.stdout.strip()[:12]  # Use short hash (12 chars)
        
        return (branch, commit_hash)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return (None, None)


def generate_asset_key(repo_path: Path, branch: Optional[str] = None, commit: Optional[str] = None) -> str:
    """Generate a unique asset key based on repository path, branch, and commit.
    
    The key format: repo_map_{repo_name}_{branch}_{commit_hash}
    If branch or commit is None, uses "unknown" as placeholder.
    
    Args:
        repo_path: Path to the repository.
        branch: Git branch name (optional).
        commit: Git commit hash (optional).
    
    Returns:
        A unique string key for the asset.
    """
    repo_path = Path(repo_path).resolve()
    repo_name = repo_path.name or "unknown_repo"
    # Sanitize repo name for use in file paths
    repo_name = repo_name.replace("/", "_").replace("\\", "_").replace("..", "")
    
    branch = branch or "unknown_branch"
    commit = commit or "unknown_commit"
    
    # Sanitize branch and commit
    branch = branch.replace("/", "_").replace("\\", "_")
    commit = commit.replace("/", "_").replace("\\", "_")
    
    # Generate key
    key = f"repo_map_{repo_name}_{branch}_{commit}"
    
    # Ensure key is not too long (some filesystems have limits)
    if len(key) > 200:
        # Use hash for very long keys
        key_hash = hashlib.md5(key.encode()).hexdigest()[:12]
        key = f"repo_map_{repo_name}_{key_hash}"
    
    return key


def get_git_diff(repo_path: Path, base: str, head: str = "HEAD") -> str:
    """Get Git diff using triple-dot syntax.
    
    This function executes `git diff {base}...{head}` in the specified repository
    to get all changes that occurred after the branches diverged.
    
    Args:
        repo_path: Path to the Git repository.
        base: Target branch (e.g., "main", "master").
        head: Source branch or commit (default: "HEAD").
    
    Returns:
        The Git diff content as a string.
    
    Raises:
        ValueError: If repo_path is not a valid Git repository.
        subprocess.CalledProcessError: If git diff command fails.
    """
    repo_path = Path(repo_path).resolve()
    
    if not repo_path.exists():
        raise ValueError(f"Repository path does not exist: {repo_path}")
    
    if not repo_path.is_dir():
        raise ValueError(f"Repository path must be a directory: {repo_path}")
    
    # Check if it's a Git repository
    # Try to find .git directory (could be a file for worktrees or submodules)
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        # Try using git rev-parse to check if it's a git repo
        try:
            subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=repo_path,
                capture_output=True,
                check=True
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise ValueError(f"Not a Git repository: {repo_path}")
    
    try:
        # Execute git diff with triple-dot syntax
        # Triple-dot (base...head) shows changes in head that are not in base
        result = subprocess.run(
            ["git", "diff", f"{base}...{head}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8"
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else "Unknown git error"
        # Provide more helpful error messages
        if "fatal:" in error_msg.lower() or "error:" in error_msg.lower():
            raise ValueError(f"Git diff failed: {error_msg}")
        else:
            raise ValueError(f"Git diff failed: {error_msg}")
    except FileNotFoundError:
        raise ValueError("Git is not installed or not in PATH")


async def build_repo_map_if_needed(
    workspace_root: Path,
    branch: Optional[str] = None,
    commit: Optional[str] = None
) -> str:
    """Build repository map if it doesn't exist in storage.
    
    This function checks if the repo_map asset exists in the DAO layer for the
    specific repository, branch, and commit combination. If it doesn't exist, it
    builds and saves it. The build process is idempotent.
    
    Args:
        workspace_root: Root directory of the workspace.
        branch: Git branch name (optional). If None, will try to detect from Git.
        commit: Git commit hash (optional). If None, will try to detect from Git.
    
    Returns:
        The asset key used for storage.
    """
    try:
        # Try to get Git info if not provided
        if branch is None or commit is None:
            detected_branch, detected_commit = get_git_info(workspace_root)
            branch = branch or detected_branch
            commit = commit or detected_commit
        
        # Generate unique asset key
        asset_key = generate_asset_key(workspace_root, branch, commit)
        
        # Initialize storage
        storage = get_storage()
        await storage.connect()
        
        # Check if repo_map already exists for this specific repo/branch/commit
        exists = await storage.exists("assets", asset_key)
        
        if exists:
            print(f"✅ Repository map already exists in storage (key: {asset_key})")
            return asset_key
        
        # Build the repo map (will save to DAO automatically with the unique key)
        print(f"🔨 Building repository map (key: {asset_key})...")
        builder = RepoMapBuilder()
        repo_map_data = await builder.build(workspace_root, asset_key=asset_key)
        
        print(f"✅ Repository map built and saved ({repo_map_data.get('file_count', 0)} files)")
        return asset_key
    
    except Exception as e:
        print(f"⚠️  Warning: Could not build repo map: {e}")
        # Continue anyway - agent can still work without repo map
        # Return a fallback key
        return generate_asset_key(workspace_root, branch, commit)


def get_repo_name(workspace_root: Path) -> str:
    """Get a recognizable repository name from workspace root.
    
    Args:
        workspace_root: Path to the workspace root.
    
    Returns:
        A recognizable repository name. If workspace_root is ".", returns a descriptive name.
    """
    workspace_root = Path(workspace_root).resolve()
    repo_name = workspace_root.name
    
    # Handle edge cases where name might be empty or "."
    if repo_name in [".", ""] or len(repo_name) == 0:
        # Try to use the parent directory name or a default
        parent_name = workspace_root.parent.name
        if parent_name and parent_name not in [".", ""]:
            return f"{parent_name}_workspace"
        return "current_workspace"
    
    return repo_name


def save_observations_to_log(
    results: dict,
    workspace_root: Path,
    config: Config
) -> Path:
    """Save agent observations to a log file.
    
    Log file structure: log/repo_name/model_name/timestamp/observations.log
    
    Args:
        results: The final state dictionary from the workflow.
        workspace_root: Root directory of the workspace.
        config: Configuration object.
    
    Returns:
        Path to the saved log file.
    """
    metadata = results.get("metadata", {})
    observations = metadata.get("agent_observations", [])
    
    if not observations:
        return None
    
    # Get repo name
    repo_name = get_repo_name(workspace_root)
    # Sanitize repo name for filesystem
    repo_name = repo_name.replace("/", "_").replace("\\", "_").replace("..", "")
    
    # Get model name from metadata or config
    model_name = metadata.get("config_provider", config.llm.provider)
    if not model_name:
        model_name = "unknown"
    # Sanitize model name
    model_name = model_name.replace("/", "_").replace("\\", "_")
    
    # Generate timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Create log directory structure
    log_dir = Path("log") / repo_name / model_name / timestamp
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Save observations to log file
    log_file = log_dir / "observations.log"
    
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(f"Agent Observations Log\n")
        f.write(f"{'=' * 80}\n")
        f.write(f"Repository: {repo_name}\n")
        f.write(f"Model: {model_name}\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        f.write(f"Total Observations: {len(observations)}\n")
        f.write(f"{'=' * 80}\n\n")
        
        for i, obs in enumerate(observations, 1):
            f.write(f"Observation {i}:\n")
            f.write(f"{'-' * 80}\n")
            f.write(f"{obs}\n")
            f.write(f"\n")
        
        # Also save tool results if available
        tool_results = metadata.get("agent_tool_results", [])
        if tool_results:
            f.write(f"\n{'=' * 80}\n")
            f.write(f"Tool Results: {len(tool_results)}\n")
            f.write(f"{'=' * 80}\n\n")
            for i, tr in enumerate(tool_results, 1):
                f.write(f"Tool Call {i}:\n")
                f.write(f"{'-' * 80}\n")
                f.write(f"Tool: {tr.get('tool', 'unknown')}\n")
                f.write(f"Input: {json.dumps(tr.get('input', {}), indent=2, ensure_ascii=False)}\n")
                f.write(f"Result: {json.dumps(tr.get('result', {}), indent=2, ensure_ascii=False)}\n")
                f.write(f"\n")
    
    return log_file


def print_review_results(results: dict, workspace_root: Path = None, config: Config = None) -> None:
    """Print the review results in a formatted way.
    
    Args:
        results: The final state dictionary from the workflow.
        workspace_root: Optional workspace root path for log saving.
        config: Optional configuration object for log saving.
    """
    print("\n" + "=" * 80)
    print("CODE REVIEW RESULTS")
    print("=" * 80)
    
    # Focus files
    focus_files = results.get("focus_files", [])
    print(f"\n📋 Focus Files ({len(focus_files)}):")
    for i, file_path in enumerate(focus_files, 1):
        print(f"  {i}. {file_path}")
    
    # Issues
    issues = results.get("identified_issues", [])
    print(f"\n🔍 Issues Found ({len(issues)}):")
    
    if not issues:
        print("  ✅ No issues found!")
    else:
        # Group by severity
        by_severity = {"error": [], "warning": [], "info": []}
        for issue in issues:
            severity = issue.get("severity", "info")
            by_severity.get(severity, by_severity["info"]).append(issue)
        
        for severity in ["error", "warning", "info"]:
            severity_issues = by_severity[severity]
            if severity_issues:
                icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}[severity]
                print(f"\n  {icon} {severity.upper()} ({len(severity_issues)}):")
                for issue in severity_issues:
                    file_path = issue.get("file", "unknown")
                    line = issue.get("line", 0)
                    message = issue.get("message", "")
                    suggestion = issue.get("suggestion", "")
                    
                    print(f"    • {file_path}:{line}")
                    print(f"      {message}")
                    if suggestion:
                        print(f"      💡 Suggestion: {suggestion}")
    
    # Metadata
    metadata = results.get("metadata", {})
    if metadata:
        print(f"\n📊 Metadata:")
        for key, value in metadata.items():
            # Skip printing observations in metadata (will be in log file)
            if key == "agent_observations":
                print(f"  • {key}: [{len(value) if isinstance(value, list) else 0} observations] (saved to log)")
            elif key == "agent_tool_results":
                print(f"  • {key}: [{len(value) if isinstance(value, list) else 0} tool calls] (saved to log)")
            else:
                print(f"  • {key}: {value}")
    
    # Save observations to log file
    if workspace_root and config:
        try:
            log_file = save_observations_to_log(results, workspace_root, config)
            if log_file:
                print(f"\n📝 Observations saved to: {log_file}")
        except Exception as e:
            print(f"\n⚠️  Warning: Could not save observations to log: {e}")
    
    print("\n" + "=" * 80)


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments.
    
    Returns:
        Parsed arguments namespace.
    """
    parser = argparse.ArgumentParser(
        description="AI Code Review Agent - Analyze Git PR diffs using LLM agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
        Examples:
        # Git branch mode: compare feature-x branch with main
        python main.py --repo ./project --base main --head feature-x
        
        # Git branch mode: compare current HEAD with main
        python main.py --repo ./project --base main
        
        # Local diff file mode
        python main.py --repo ./project --diff ./changes.diff
                """
    )
    
    parser.add_argument(
        "--repo",
        type=str,
        required=True,
        help="Path to the repository to review (required)"
    )
    
    # Diff source: either Git branches or local file
    parser.add_argument(
        "--base",
        type=str,
        default=None,
        help="Target branch for Git diff mode (e.g., 'main', 'master')"
    )
    
    parser.add_argument(
        "--diff",
        type=str,
        default=None,
        help="Path to a local .diff file (alternative to --base/--head). Takes priority if both are provided."
    )
    
    parser.add_argument(
        "--head",
        type=str,
        default="HEAD",
        help="Source branch or commit for Git diff mode (default: HEAD). Only used with --base."
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default="review_results.json",
        help="Path to save the review results JSON file (default: review_results.json)"
    )
    
    return parser.parse_args()


async def main():
    """Main entry point for the code review agent."""
    args = parse_arguments()
    
    print("🚀 AI Code Review Agent - MVP")
    print("=" * 80)
    
    # Validate and resolve repository path
    repo_path = Path(args.repo).resolve()
    if not repo_path.exists():
        print(f"❌ Repository path does not exist: {repo_path}")
        sys.exit(1)
    if not repo_path.is_dir():
        print(f"❌ Repository path must be a directory: {repo_path}")
        sys.exit(1)
    
    print(f"📁 Repository: {repo_path}")
    
    # Load configuration and set workspace root to repo path
    config = Config.load_default()
    config.system.workspace_root = repo_path
    
    print(f"📝 Configuration loaded: LLM Provider = {config.llm.provider}")
    print(f"📁 Workspace root: {config.system.workspace_root}")
    
    # Get diff: either from Git or from file
    pr_diff = None
    
    # Check if both --diff and --base are provided (warn that --diff takes priority)
    if args.diff and args.base:
        print(f"⚠️  Warning: Both --diff and --base provided. Using --diff (file mode) and ignoring --base.")
    
    if args.diff:
        # Mode B: Local diff file (takes priority)
        diff_path = Path(args.diff)
        if not diff_path.is_absolute():
            # If relative, try relative to repo_path first, then current directory
            repo_relative = repo_path / diff_path
            if repo_relative.exists():
                diff_path = repo_relative
            else:
                diff_path = diff_path.resolve()
        
        print(f"\n📂 Loading diff from file: {diff_path}")
        try:
            pr_diff = load_diff_from_file(diff_path)
            print(f"✅ Diff loaded ({len(pr_diff)} characters)")
        except Exception as e:
            print(f"❌ Error loading diff file: {e}")
            sys.exit(1)
    
    elif args.base:
        # Mode A: Git branch diff
        print(f"\n🔀 Getting Git diff: {args.base}...{args.head}")
        try:
            pr_diff = get_git_diff(repo_path, args.base, args.head)
            if not pr_diff or len(pr_diff.strip()) == 0:
                print(f"⚠️  Warning: Git diff is empty. No changes found between {args.base} and {args.head}")
            else:
                print(f"✅ Git diff retrieved ({len(pr_diff)} characters)")
        except Exception as e:
            print(f"❌ Error getting Git diff: {e}")
            sys.exit(1)
    
    else:
        # Neither --diff nor --base provided
        print("❌ Error: Must provide either --base (for Git mode) or --diff (for file mode)")
        print("   Examples:")
        print("     python main.py --repo ./project --base main --head feature-x")
        print("     python main.py --repo ./project --diff ./changes.diff")
        sys.exit(1)
    
    if not pr_diff:
        print("❌ Error: No diff content available")
        sys.exit(1)
    
    print(f"📝 Processing Git diff ({len(pr_diff)} characters)...")
    
    # Step 1: Initialize Storage (DAO layer)
    print("\n💾 Initializing storage backend...")
    storage = get_storage()
    await storage.connect()
    print("✅ Storage initialized")
    
    # Step 2: Build Assets if needed
    print("\n📦 Checking assets...")
    # Get Git info for asset key generation
    branch = None
    commit = None
    if args.base:
        # Git mode: get info from head branch
        branch, commit = get_git_info(repo_path, args.head)
    else:
        # Diff file mode: try to get current Git info
        branch, commit = get_git_info(repo_path)
    
    asset_key = await build_repo_map_if_needed(repo_path, branch=branch, commit=commit)
    
    # Store asset_key in config for tools to use
    config.system.asset_key = asset_key
    
    # Step 3 & 4: Initialize and Run Autonomous ReAct Agent
    print("\n🤖 Initializing autonomous ReAct agent...")
    print("  → Agent will autonomously:")
    
    try:
        results = await run_react_agent(
            pr_diff=pr_diff,
            config=config
        )
        
        # Print results
        print_review_results(results, workspace_root=repo_path, config=config)
        
        # Save results to file
        output_file = Path(args.output)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Results saved to: {output_file}")
        
    except Exception as e:
        print(f"\n❌ Error running agent: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
