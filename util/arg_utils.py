"""参数验证和 diff 加载工具。"""

import sys
from pathlib import Path
from typing import Optional, Tuple

from util.git_utils import get_git_diff, get_git_info


def validate_repo_path(repo_path: Path) -> Path:
    """验证并解析仓库路径。
    
    Raises:
        SystemExit: 路径无效。
    """
    repo_path = Path(repo_path).resolve()
    
    if not repo_path.exists():
        print(f"❌ Repository path does not exist: {repo_path}")
        sys.exit(1)
    
    if not repo_path.is_dir():
        print(f"❌ Repository path must be a directory: {repo_path}")
        sys.exit(1)
    
    return repo_path


def load_diff_from_args(
    args,
    repo_path: Path
) -> Tuple[str, Optional[str], Optional[str]]:
    """根据命令行参数从 Git 加载 diff 内容。
    
    此函数加载 base 和 head 分支/提交之间的 Git diff。
    它验证参数并提供有用的错误消息。
    
    Returns:
        (diff_content, branch, commit) 元组。
    
    Raises:
        SystemExit: 参数无效或无法加载 diff。
    """
    # Validate that --base and --head are provided
    if not args.base:
        print("❌ Error: --base is required")
        print("   Examples:")
        print("     python main.py --repo ./project --base main --head feature-x")
        print("     python main.py --repo ./project --base main --head HEAD")
        sys.exit(1)
    
    if not args.head:
        print("❌ Error: --head is required")
        print("   Examples:")
        print("     python main.py --repo ./project --base main --head feature-x")
        print("     python main.py --repo ./project --base main --head HEAD")
        sys.exit(1)
    
    # Get Git diff
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
    
    # Get Git info from head branch for asset key generation
    branch, commit = get_git_info(repo_path, args.head)
    
    if not pr_diff:
        print("❌ Error: No diff content available")
        sys.exit(1)
    
    print(f"📝 Processing Git diff ({len(pr_diff)} characters)...")
    
    return (pr_diff, branch, commit)
