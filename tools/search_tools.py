"""Search tools for querying the repository.

This module provides tools for searching and querying the codebase structure.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import Field
from tools.base import BaseTool


class SearchRepoTool(BaseTool):
    """Tool for searching the repository structure.
    
    This tool queries the RepoMap asset to find files matching certain criteria.
    It wraps the RepoMapBuilder's query functionality.
    """
    
    repo_map_asset: Optional[Dict[str, Any]] = Field(
        default=None,
        description="The RepoMap asset data dictionary"
    )
    
    def __init__(self, repo_map_asset: Optional[Dict[str, Any]] = None, **kwargs):
        """Initialize the SearchRepoTool.
        
        Args:
            repo_map_asset: The RepoMap asset data dictionary. If None, the tool
                           will need to receive it via the run method.
            **kwargs: Additional arguments passed to BaseTool.
        """
        super().__init__(
            name="search_repo",
            description="Search the repository structure for files matching a query",
            repo_map_asset=repo_map_asset,
            **kwargs
        )
    
    async def run(self, query: str, repo_map_asset: Dict[str, Any] = None, **kwargs: Any) -> Dict[str, Any]:
        """Search the repository for files matching the query.
        
        Args:
            query: Search query string (e.g., "Python files", ".py", "test").
            repo_map_asset: Optional RepoMap asset data. If not provided, uses
                           the instance's repo_map_asset.
            **kwargs: Additional search parameters.
        
        Returns:
            A dictionary containing:
                - "query": The original query string.
                - "matches": List of matching file paths.
                - "match_count": Number of matches found.
                - "error": Optional error message.
        """
        try:
            asset_data = repo_map_asset or self.repo_map_asset
            if asset_data is None:
                return {
                    "query": query,
                    "matches": [],
                    "match_count": 0,
                    "error": "No RepoMap asset provided"
                }
            
            files = asset_data.get("files", [])
            query_lower = query.lower()
            
            # Simple keyword matching for MVP
            # Future: could use more sophisticated search (regex, AST queries, etc.)
            matching_files = [
                f for f in files
                if query_lower in f.lower() or 
                   query_lower in Path(f).suffix.lower() or
                   query_lower in Path(f).stem.lower()
            ]
            
            return {
                "query": query,
                "matches": matching_files,
                "match_count": len(matching_files),
                "error": None
            }
        except Exception as e:
            return {
                "query": query,
                "matches": [],
                "match_count": 0,
                "error": f"Error searching repository: {str(e)}"
            }

