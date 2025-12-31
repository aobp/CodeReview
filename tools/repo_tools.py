"""代码审查系统的仓库工具。"""

from typing import Any, Dict, Optional
from pydantic import Field
from tools.base import BaseTool
from dao.factory import get_storage


class FetchRepoMapTool(BaseTool):
    """从存储中获取仓库地图的工具。"""
    
    asset_key: Optional[str] = Field(
        default=None,
        description="Asset key for the repository map. If None, uses default 'repo_map'."
    )
    
    def __init__(self, asset_key: Optional[str] = None, **kwargs):
        """初始化仓库地图获取工具。"""
        super().__init__(
            name="fetch_repo_map",
            description="Fetch the repository map to understand the project structure. Returns a summary of files and directory layout.",
            asset_key=asset_key,
            **kwargs
        )
    
    async def run(self, **kwargs: Any) -> Dict[str, Any]:
        """从存储中获取仓库地图并返回摘要。
        
        Returns:
            包含 "summary" 和 "file_count" 的字典。
                - "files": List of file paths (truncated if too many).
                - "error": Optional error message if fetching failed.
        """
        try:
            storage = get_storage()
            await storage.connect()
            
            # Use asset_key if set, otherwise fall back to "repo_map" for backward compatibility
            key = self.asset_key if self.asset_key else "repo_map"
            repo_map_data = await storage.load("assets", key)
            
            if repo_map_data is None:
                return {
                    "summary": "Repository map not found. Please build the repository map first.",
                    "file_count": 0,
                    "files": [],
                    "error": "Repository map not found in storage"
                }
            
            # Extract key information
            file_tree = repo_map_data.get("file_tree", "No file tree available")
            file_count = repo_map_data.get("file_count", 0)
            files = repo_map_data.get("files", [])
            source_path = repo_map_data.get("source_path", "unknown")
            
            # Create a summary string
            # Limit file list to first 50 for readability
            files_preview = files[:50]
            files_display = "\n".join(f"  - {f}" for f in files_preview)
            if len(files) > 50:
                files_display += f"\n  ... and {len(files) - 50} more files"
            
            summary = f"""Repository Structure Summary:
Source Path: {source_path}
Total Files: {file_count}

File Tree:
{file_tree}

Key Files (first 50):
{files_display}
"""
            
            return {
                "summary": summary,
                "file_count": file_count,
                "files": files_preview,  # Return preview only
                "all_files": files,  # Full list available if needed
                "source_path": source_path,
                "error": None
            }
        except Exception as e:
            return {
                "summary": "",
                "file_count": 0,
                "files": [],
                "error": f"Error fetching repository map: {str(e)}"
            }
