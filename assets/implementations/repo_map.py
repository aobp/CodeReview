"""仓库地图构建器实现。

实现 RepoMapBuilder，生成代码库的文件树表示。
对于 MVP，这是简化版本，尚未使用 tree-sitter，但为未来增强提供了接口。

构建器现在使用 DAO 层进行持久化，使其幂等并为未来的数据库后端做准备。
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from assets.base import BaseAssetBuilder
from dao.factory import get_storage


class RepoMapBuilder(BaseAssetBuilder):
    """生成仓库地图资产的构建器。
    
    RepoMap 将代码库的结构表示为文件树。
    对于 MVP，此实现仅遍历目录并生成文本表示。
    未来版本将使用 tree-sitter 进行 AST 分析。
    """
    
    def __init__(self, asset_type: str = "repo_map", supported_extensions: List[str] = None):
        """初始化 RepoMapBuilder。"""
        super().__init__(asset_type)
        if supported_extensions is None:
            self.supported_extensions = [".py", ".js", ".ts", ".go", ".java", ".cpp", ".c", ".h"]
        else:
            self.supported_extensions = supported_extensions
    
    async def build(self, source_path: Path, **kwargs: Any) -> Dict[str, Any]:
        """从源目录构建仓库地图并保存到 DAO。
        
        此方法遍历目录结构并生成文件树表示。
        结果自动保存到 DAO 层。此方法是幂等的——多次调用将覆盖先前的数据。
        """
        source_path = Path(source_path).resolve()
        if not source_path.exists():
            raise ValueError(f"Source path does not exist: {source_path}")
        
        if not source_path.is_dir():
            raise ValueError(f"Source path must be a directory: {source_path}")
        
        max_depth = kwargs.get("max_depth", 10)
        exclude_patterns = kwargs.get("exclude_patterns", [".git", "__pycache__", "node_modules", ".venv"])
        
        file_tree_lines: List[str] = []
        files: List[str] = []
        
        def should_exclude(path: Path) -> bool:
            """Check if a path should be excluded."""
            path_str = str(path)
            return any(pattern in path_str for pattern in exclude_patterns)
        
        def build_tree(current_path: Path, prefix: str = "", depth: int = 0) -> None:
            """Recursively build the file tree representation."""
            if depth > max_depth:
                return
            
            if should_exclude(current_path):
                return
            
            if current_path.is_file():
                if any(current_path.suffix == ext for ext in self.supported_extensions):
                    relative_path = current_path.relative_to(source_path)
                    file_tree_lines.append(f"{prefix}📄 {current_path.name}")
                    files.append(str(relative_path))
            elif current_path.is_dir():
                relative_path = current_path.relative_to(source_path)
                if relative_path != Path("."):
                    file_tree_lines.append(f"{prefix}📁 {current_path.name}/")
                
                try:
                    entries = sorted(current_path.iterdir(), key=lambda p: (p.is_file(), p.name))
                    for i, entry in enumerate(entries):
                        is_last = i == len(entries) - 1
                        new_prefix = prefix + ("    " if is_last else "│   ")
                        build_tree(entry, new_prefix, depth + 1)
                except PermissionError:
                    pass
        
        # Start building from the root
        file_tree_lines.append(f"📁 {source_path.name}/")
        build_tree(source_path, "", 0)
        
        file_tree = "\n".join(file_tree_lines)
        
        # Build the asset data
        asset_data = {
            "file_tree": file_tree,
            "file_count": len(files),
            "files": files,
            "source_path": str(source_path)
        }
        
        # Get asset key from kwargs, default to "repo_map" for backward compatibility
        asset_key = kwargs.get("asset_key", "repo_map")
        
        # Save to DAO (idempotent - will overwrite if exists)
        storage = get_storage()
        await storage.connect()
        await storage.save("assets", asset_key, asset_data)
        
        return asset_data
    
    async def query(self, query: str, **kwargs: Any) -> Dict[str, Any]:
        """Query the repository map.
        
        For MVP, this is a simple text search. Future versions will support
        more sophisticated queries using tree-sitter ASTs.
        
        Args:
            query: Query string (e.g., "find all Python files").
            **kwargs: Additional query parameters.
        
        Returns:
            A dictionary containing query results.
        """
        # For MVP, we'll do a simple keyword search
        # In the future, this will use tree-sitter for AST queries
        asset_data = kwargs.get("asset_data", {})
        files = asset_data.get("files", [])
        
        query_lower = query.lower()
        matching_files = [
            f for f in files
            if query_lower in f.lower() or query_lower in Path(f).suffix.lower()
        ]
        
        return {
            "query": query,
            "matches": matching_files,
            "match_count": len(matching_files)
        }
    
    async def save(self, output_path: Path, asset_data: Dict[str, Any]) -> None:
        """Save the repository map using DAO.
        
        This method is kept for backward compatibility but now uses DAO.
        The output_path parameter is ignored - data is saved via DAO.
        
        Args:
            output_path: Ignored (kept for interface compatibility).
            asset_data: The asset data dictionary to save.
        """
        storage = get_storage()
        await storage.connect()
        await storage.save("assets", "repo_map", asset_data)
    
    async def load(self, input_path: Path) -> Optional[Dict[str, Any]]:
        """Load the repository map from DAO.
        
        This method is kept for backward compatibility but now uses DAO.
        The input_path parameter is ignored - data is loaded via DAO.
        
        Args:
            input_path: Ignored (kept for interface compatibility).
        
        Returns:
            A dictionary containing the loaded asset data, or None if not found.
        """
        storage = get_storage()
        await storage.connect()
        return await storage.load("assets", "repo_map")

