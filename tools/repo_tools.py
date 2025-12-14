"""Repository tools for the code review system.

This module provides tools for accessing repository structure and metadata
stored in the DAO layer.
"""

from typing import Any, Dict
from tools.base import BaseTool
from dao.factory import get_storage


class FetchRepoMapTool(BaseTool):
    """Tool for fetching repository map from storage.
    
    This tool loads the repository map asset from the DAO layer and returns
    a summary string that agents can use to understand the project structure.
    The agent uses this tool to "perceive" the codebase structure rather than
    relying on hardcoded context.
    """
    
    def __init__(self):
        """Initialize the FetchRepoMapTool."""
        super().__init__(
            name="fetch_repo_map",
            description="Fetch the repository map to understand the project structure. Returns a summary of files and directory layout."
        )
    
    async def run(self, **kwargs: Any) -> Dict[str, Any]:
        """Fetch repository map from storage and return summary.
        
        Args:
            **kwargs: Additional parameters (not used currently).
        
        Returns:
            A dictionary containing:
                - "summary": A string summary of the repository structure.
                - "file_count": Number of files in the repository.
                - "files": List of file paths (truncated if too many).
                - "error": Optional error message if fetching failed.
        """
        try:
            storage = get_storage()
            await storage.connect()
            
            repo_map_data = await storage.load("assets", "repo_map")
            
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
