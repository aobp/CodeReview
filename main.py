"""AI 代码审查系统主入口。

工作流程：
1. 初始化存储（DAO 层）
2. 构建资产（RepoMap，如需要）
3. 初始化多智能体工作流
4. 执行工作流
5. 显示审查结果
"""


import asyncio
import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from core.config import Config
from dao.factory import get_storage
from assets.implementations.repo_map import RepoMapBuilder
from agents.workflow import run_multi_agent_workflow
from external_tools.syntax_checker import CheckerFactory, get_config
from external_tools.syntax_checker.config_loader import create_checker_instance
from util import (
    generate_asset_key,
    get_git_info,
    load_diff_from_args,
    print_review_results,
    validate_repo_path,
    ensure_head_version,
)
from util.git_utils import extract_files_from_diff, get_changed_files


def _make_serializable(obj: dict) -> dict:
    """移除字典中的不可序列化对象（如 LLMProvider、Config、tools）。
    
    Args:
        obj: 可能包含不可序列化对象的字典。
    
    Returns:
        仅包含可序列化值的字典。
    """
    if not isinstance(obj, dict):
        return obj
    
    result = {}
    for key, value in obj.items():
        if key == "metadata":
            # Clean metadata: keep only serializable values
            if isinstance(value, dict):
                clean_metadata = {}
                for meta_key, meta_value in value.items():
                    # Skip non-serializable objects
                    if meta_key in ["llm_provider", "config", "tools"]:
                        # Store a string representation instead
                        if meta_key == "config":
                            clean_metadata[meta_key] = {
                                "llm_provider": str(type(meta_value.llm.provider).__name__) if hasattr(meta_value, "llm") else None,
                                "model": meta_value.llm.model if hasattr(meta_value, "llm") else None,
                            }
                        else:
                            clean_metadata[meta_key] = str(type(meta_value).__name__)
                    else:
                        # Try to serialize, skip if not serializable
                        try:
                            json.dumps(meta_value)
                            clean_metadata[meta_key] = meta_value
                        except (TypeError, ValueError):
                            clean_metadata[meta_key] = str(meta_value)
                result[key] = clean_metadata
            else:
                result[key] = value
        elif isinstance(value, dict):
            result[key] = _make_serializable(value)
        elif isinstance(value, list):
            result[key] = [
                _make_serializable(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            # Try to serialize, skip if not serializable
            try:
                json.dumps(value)
                result[key] = value
            except (TypeError, ValueError):
                result[key] = str(value)
    
    return result


async def run_syntax_checking(
    repo_path: Path,
    pr_diff: str,
    args: argparse.Namespace
) -> List[dict]:
    """对变更文件执行语法/静态检查。
    
    Args:
        repo_path: 仓库根路径。
        pr_diff: Git diff 内容。
        args: 命令行参数。
    
    Returns:
        检查错误列表，每个错误包含：file, line, message, severity, code。
    """
    try:
        # Get changed files from Git
        try:
            changed_files = get_changed_files(repo_path, args.base, args.head)
        except Exception as e:
            print(f"  ⚠️  Warning: Could not get changed files from Git: {e}")
            # Fallback: try to extract from diff
            changed_files = extract_files_from_diff(pr_diff)
        
        if not changed_files:
            return []
        
        # Group files by checker
        checker_groups = CheckerFactory.get_checkers_for_files(changed_files)
        
        if not checker_groups:
            return []
        
        # Run all checkers
        all_errors = []
        config = get_config()
        
        for checker_class, files in checker_groups.items():
            try:
                # Create checker instance with configuration (if available)
                checker = create_checker_instance(checker_class, config)
                
                errors = await checker.check(repo_path, files)
                # Convert LintError objects to dictionaries
                all_errors.extend([
                    {
                        "file": error.file,
                        "line": error.line,
                        "message": error.message,
                        "severity": error.severity,
                        "code": error.code
                    }
                    for error in errors
                ])
            except Exception as e:
                # Gracefully handle checker failures
                print(f"  ⚠️  Warning: {checker_class.__name__} failed: {e}")
                continue
        
        return all_errors
    
    except Exception as e:
        # Gracefully handle any errors in syntax checking
        print(f"  ⚠️  Warning: Syntax checking failed: {e}")
        return []


async def build_repo_map_if_needed(
    workspace_root: Path,
    branch: Optional[str] = None,
    commit: Optional[str] = None
) -> str:
    """如需要则构建仓库地图（幂等操作）。
    
    Args:
        workspace_root: 工作区根目录。
        branch: Git 分支名（可选，未提供则从 Git 检测）。
        commit: Git 提交哈希（可选，未提供则从 Git 检测）。
    
    Returns:
        用于存储的资产键。
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


def parse_arguments() -> argparse.Namespace:
    """解析命令行参数。
    
    Returns:
        解析后的参数命名空间。
    """
    parser = argparse.ArgumentParser(
        description="AI Code Review Agent - Analyze Git PR diffs using LLM agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
        Examples:
        # Compare feature-x branch with main
        python main.py --repo ./project --base main --head feature-x
        
        # Compare current HEAD with main
        python main.py --repo ./project --base main --head HEAD
                """
    )
    
    parser.add_argument(
        "--repo",
        type=str,
        required=True,
        help="Path to the repository to review (required)"
    )
    
    parser.add_argument(
        "--base",
        type=str,
        required=True,
        help="Target branch for Git diff (e.g., 'main', 'master')"
    )
    
    parser.add_argument(
        "--head",
        type=str,
        required=True,
        help="Source branch or commit for Git diff (e.g., 'feature-x', 'HEAD')"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        default="review_results.json",
        help="Path to save the review results JSON file (default: review_results.json)"
    )
    
    return parser.parse_args()


async def main():
    """代码审查系统主入口。"""
    args = parse_arguments()
    
    print("🚀 AI Code Review Agent - MVP")
    print("=" * 80)
    
    # Validate and resolve repository path
    repo_path = validate_repo_path(Path(args.repo))
    print(f"📁 Repository: {repo_path}")
    
    # Load configuration and set workspace root to repo path
    config = Config.load_default()
    config.system.workspace_root = repo_path
    
    print(f"📝 Configuration loaded: LLM Provider = {config.llm.provider}")
    print(f"📁 Workspace root: {config.system.workspace_root}")
    
    # Ensure repository is on HEAD version (not base version) before review
    try:
        print(f"\n🔀 Ensuring repository is on HEAD version ({args.head})...")
        ensure_head_version(repo_path, args.head)
        print(f"✅ Repository is on HEAD version")
    except Exception as e:
        print(f"⚠️  Warning: Could not ensure HEAD version: {e}")
        print(f"   Continuing with current version...")
    
    # Load diff from Git (includes argument validation)
    pr_diff, branch, commit = load_diff_from_args(args, repo_path)
    
    # Step 1: Initialize Storage (DAO layer)
    print("\n💾 Initializing storage backend...")
    storage = get_storage()
    await storage.connect()
    print("✅ Storage initialized")
    
    # Step 2: Build Assets if needed
    print("\n📦 Checking assets...")
    # Git info already retrieved in load_diff_from_args
    asset_key = await build_repo_map_if_needed(repo_path, branch=branch, commit=commit)
    
    # Store asset_key in config for tools to use
    config.system.asset_key = asset_key
    
    # Step 2.5: Run Pre-Agent Syntax/Lint Checking
    print("\n🔍 Running pre-agent syntax/lint checking...")
    lint_errors = await run_syntax_checking(
        repo_path=repo_path,
        pr_diff=pr_diff,
        args=args
    )
    
    if lint_errors:
        print(f"  ⚠️  Found {len(lint_errors)} linting error(s):")
        for error in lint_errors[:10]:  # Show first 10
            file_path = error.get("file", "unknown")
            line = error.get("line", 0)
            message = error.get("message", "")
            severity = error.get("severity", "error")
            icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(severity, "•")
            print(f"    {icon} {file_path}:{line} - {message}")
        if len(lint_errors) > 10:
            print(f"    ... and {len(lint_errors) - 10} more")
    else:
        print("  ✅ No linting errors found")
    
    # Step 3 & 4: Initialize and Run Multi-Agent Workflow
    print("\n🤖 Initializing multi-agent workflow...")
    print("  → Workflow will:")
    print("    1. Analyze file intents in parallel")
    print("    2. Manager routes tasks to expert agents")
    print("    3. Expert agents validate risks with concurrency control")
    print("    4. Generate final review report")
    
    # Get changed files list for the workflow
    try:
        changed_files = get_changed_files(repo_path, args.base, args.head)
    except Exception as e:
        print(f"  ⚠️  Warning: Could not get changed files from Git: {e}")
        # Fallback: try to extract from diff
        try:
            changed_files = extract_files_from_diff(pr_diff)
        except Exception as e2:
            print(f"  ⚠️  Warning: Could not extract changed files from diff: {e2}")
            changed_files = []
    
    if not changed_files:
        print("  ⚠️  Warning: No changed files detected, workflow may not produce results")
    
    try:
        results = await run_multi_agent_workflow(
            diff_context=pr_diff,
            changed_files=changed_files,
            config=config,
            lint_errors=lint_errors
        )
        
        # Print results
        print_review_results(results, workspace_root=repo_path, config=config)
        
        # Save results to file (clean non-serializable objects from metadata)
        output_file = Path(args.output)
        
        # Create a serializable copy of results
        serializable_results = _make_serializable(results)
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(serializable_results, f, indent=2, ensure_ascii=False)
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
