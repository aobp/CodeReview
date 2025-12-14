"""Repository map builder implementation.

This module implements a RepoMapBuilder that generates a file tree representation
of the codebase. For MVP, this is a simplified version that doesn't use tree-sitter
yet, but provides the interface for future enhancement.
"""

import os
from pathlib import Path
from typing import Any, Dict, List
from assets.base import BaseAssetBuilder


class RepoMapBuilder(BaseAssetBuilder):
    """Builder for generating repository map assets.
    
    The RepoMap represents the structure of the codebase as a file tree.
    For MVP, this implementation simply traverses the directory and generates
    a text representation. Future versions will use tree-sitter for AST analysis.
    
    Attributes:
        asset_type: Always "repo_map" for this builder.
        supported_extensions: List of file extensions to include in the map.
    """
    
    def __init__(self, asset_type: str = "repo_map", supported_extensions: List[str] = None):
        """Initialize the RepoMapBuilder.
        
        Args:
            asset_type: The asset type identifier (default: "repo_map").
            supported_extensions: List of file extensions to include (e.g., [".py", ".js"]).
                                 If None, includes common code file extensions.
        """
        super().__init__(asset_type)
        if supported_extensions is None:
            self.supported_extensions = [".py", ".js", ".ts", ".go", ".java", ".cpp", ".c", ".h"]
        else:
            self.supported_extensions = supported_extensions
    
    async def build(self, source_path: Path, **kwargs: Any) -> Dict[str, Any]:
        """Build the repository map from the source directory.
        
        This method traverses the directory structure and generates a file tree
        representation. For MVP, it's a simple text-based tree.
        
        Args:
            source_path: Path to the source code directory.
            **kwargs: Additional parameters (e.g., max_depth, exclude_patterns).
        
        Returns:
            A dictionary containing:
                - "file_tree": A string representation of the file tree.
                - "file_count": Total number of files included.
                - "files": List of file paths relative to source_path.
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
        
        return {
            "file_tree": file_tree,
            "file_count": len(files),
            "files": files,
            "source_path": str(source_path)
        }
    
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
        """Save the repository map to disk.
        
        Args:
            output_path: Path where the asset should be saved.
            asset_data: The asset data dictionary to save.
        """
        import json
        
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(asset_data, f, indent=2, ensure_ascii=False)
    
    async def load(self, input_path: Path) -> Dict[str, Any]:
        """Load the repository map from disk.
        
        Args:
            input_path: Path to the saved asset file.
        
        Returns:
            A dictionary containing the loaded asset data.
        """
        import json
        
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"Asset file not found: {input_path}")
        
        with open(input_path, "r", encoding="utf-8") as f:
            return json.load(f)

