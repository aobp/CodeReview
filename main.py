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
import json
import sys
from datetime import datetime
from pathlib import Path
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


async def build_repo_map_if_needed(workspace_root: Path) -> None:
    """Build repository map if it doesn't exist in storage.
    
    This function checks if the repo_map asset exists in the DAO layer,
    and builds it if it's missing. The build process is idempotent.
    
    Args:
        workspace_root: Root directory of the workspace.
    """
    try:
        # Initialize storage
        storage = get_storage()
        await storage.connect()
        
        # Check if repo_map already exists
        exists = await storage.exists("assets", "repo_map")
        
        if exists:
            print("✅ Repository map already exists in storage")
            return
        
        # Build the repo map (will save to DAO automatically)
        print("🔨 Building repository map...")
        builder = RepoMapBuilder()
        repo_map_data = await builder.build(workspace_root)
        
        print(f"✅ Repository map built and saved ({repo_map_data.get('file_count', 0)} files)")
    
    except Exception as e:
        print(f"⚠️  Warning: Could not build repo map: {e}")
        # Continue anyway - agent can still work without repo map


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
  # Use sample diff (default: sample.diff)
  python main.py
  
  # Load diff from file
  python main.py --diff my_changes.diff
  
  # Load diff and specify output file
  python main.py --diff my_changes.diff --output results.json
        """
    )
    
    parser.add_argument(
        "--diff",
        type=str,
        default=None,
        help="Path to the Git diff file (default: sample.diff if exists, otherwise uses built-in sample)"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default="review_results.json",
        help="Path to save the review results JSON file (default: review_results.json)"
    )
    
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="Workspace root directory (default: current directory)"
    )
    
    return parser.parse_args()


async def main():
    """Main entry point for the code review agent."""
    args = parse_arguments()
    
    print("🚀 AI Code Review Agent - MVP")
    print("=" * 80)
    
    # Load configuration
    config = Config.load_default()
    if args.workspace:
        config.system.workspace_root = Path(args.workspace).resolve()
    
    print(f"📝 Configuration loaded: LLM Provider = {config.llm.provider}")
    
    # Get workspace root
    workspace_root = config.system.workspace_root
    print(f"📁 Workspace root: {workspace_root}")
    
    # Load diff from file or use default
    pr_diff = None
    if args.diff:
        diff_path = Path(args.diff)
        print(f"\n📂 Loading diff from file: {diff_path}")
        try:
            pr_diff = load_diff_from_file(diff_path)
            print(f"✅ Diff loaded ({len(pr_diff)} characters)")
        except Exception as e:
            print(f"❌ Error loading diff file: {e}")
            sys.exit(1)
    else:
        # Try to load sample.diff if it exists
        sample_diff_path = Path("sample.diff")
        if sample_diff_path.exists():
            print(f"\n📂 Loading default sample diff: {sample_diff_path}")
            try:
                pr_diff = load_diff_from_file(sample_diff_path)
                print(f"✅ Sample diff loaded ({len(pr_diff)} characters)")
            except Exception as e:
                print(f"⚠️  Could not load sample.diff: {e}")
                print("❌ No diff file provided. Use --diff to specify a diff file.")
                sys.exit(1)
        else:
            print("❌ No diff file provided and sample.diff not found.")
            print("   Please use --diff to specify a diff file, or create sample.diff")
            sys.exit(1)
    
    print(f"📝 Processing Git diff ({len(pr_diff)} characters)...")
    
    # Step 1: Initialize Storage (DAO layer)
    print("\n💾 Initializing storage backend...")
    storage = get_storage()
    await storage.connect()
    print("✅ Storage initialized")
    
    # Step 2: Build Assets if needed
    print("\n📦 Checking assets...")
    await build_repo_map_if_needed(workspace_root)
    
    # Step 3 & 4: Initialize and Run Autonomous ReAct Agent
    print("\n🤖 Initializing autonomous ReAct agent...")
    print("  → Agent will autonomously:")
    
    try:
        results = await run_react_agent(
            pr_diff=pr_diff,
            config=config
        )
        
        # Print results
        print_review_results(results, workspace_root=workspace_root, config=config)
        
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
