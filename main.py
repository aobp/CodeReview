"""Main entry point for the AI Code Review Agent.

This script demonstrates the complete workflow:
1. Parse a Git diff
2. Build/load RepoMap
3. Run the LangGraph workflow
4. Display review results
"""

import asyncio
import argparse
import json
import sys
from pathlib import Path
from core.config import Config
from assets.implementations.repo_map import RepoMapBuilder
from assets.registry import get_registry
from agents.workflow import run_review_workflow


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


async def build_repo_map(workspace_root: Path) -> str:
    """Build or load the repository map.
    
    Args:
        workspace_root: Root directory of the workspace.
    
    Returns:
        A string summary of the repository structure.
    """
    try:
        # Register RepoMapBuilder
        registry = get_registry()
        registry.register("repo_map", RepoMapBuilder)
        
        # Create builder instance
        builder = RepoMapBuilder()
        
        # Build the repo map
        repo_map_data = await builder.build(workspace_root)
        
        # Return a summary string
        return repo_map_data.get("file_tree", "Repository structure not available")
    
    except Exception as e:
        print(f"Warning: Could not build repo map: {e}")
        return f"Repository structure unavailable: {str(e)}"


def print_review_results(results: dict) -> None:
    """Print the review results in a formatted way.
    
    Args:
        results: The final state dictionary from the workflow.
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
            print(f"  • {key}: {value}")
    
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
    
    # Build repository map
    print("\n🔨 Building repository map...")
    repo_map_summary = await build_repo_map(workspace_root)
    print("✅ Repository map built")
    
    # Run the workflow
    print("\n🔄 Running code review workflow...")
    print("  → Manager: Analyzing diff and identifying focus files...")
    print("  → Reviewer: Reviewing files and generating comments...")
    
    try:
        results = await run_review_workflow(
            pr_diff=pr_diff,
            repo_map_summary=repo_map_summary,
            config=config
        )
        
        # Print results
        print_review_results(results)
        
        # Save results to file
        output_file = Path(args.output)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Results saved to: {output_file}")
        
    except Exception as e:
        print(f"\n❌ Error running workflow: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
