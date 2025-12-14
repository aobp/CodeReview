"""File reading tools for the code review system.

This module provides tools for reading and analyzing files in the codebase.
"""

from pathlib import Path
from typing import Any, Dict
from tools.base import BaseTool


class ReadFileTool(BaseTool):
    """Tool for reading file contents.
    
    This tool reads the contents of a file and returns it along with metadata.
    It's used by agents to examine code files during the review process.
    """
    
    def __init__(self):
        """Initialize the ReadFileTool."""
        super().__init__(
            name="read_file",
            description="Read the contents of a file from the codebase"
        )
    
    async def run(self, file_path: str, **kwargs: Any) -> Dict[str, Any]:
        """Read a file and return its contents.
        
        Args:
            file_path: Path to the file to read (relative to workspace root or absolute).
            **kwargs: Additional parameters (e.g., max_lines, encoding).
        
        Returns:
            A dictionary containing:
                - "content": The file contents as a string.
                - "file_path": The resolved file path.
                - "line_count": Number of lines in the file.
                - "encoding": The encoding used.
                - "error": Optional error message if reading failed.
        """
        try:
            file_path_obj = Path(file_path)
            if not file_path_obj.is_absolute():
                # Assume relative to current working directory
                file_path_obj = Path.cwd() / file_path_obj
            
            if not file_path_obj.exists():
                return {
                    "content": "",
                    "file_path": str(file_path_obj),
                    "line_count": 0,
                    "encoding": "utf-8",
                    "error": f"File not found: {file_path_obj}"
                }
            
            encoding = kwargs.get("encoding", "utf-8")
            max_lines = kwargs.get("max_lines")
            
            with open(file_path_obj, "r", encoding=encoding) as f:
                lines = f.readlines()
                line_count = len(lines)
                
                if max_lines and line_count > max_lines:
                    content = "".join(lines[:max_lines])
                    content += f"\n... (truncated, {line_count - max_lines} more lines)"
                else:
                    content = "".join(lines)
            
            return {
                "content": content,
                "file_path": str(file_path_obj),
                "line_count": line_count,
                "encoding": encoding,
                "error": None
            }
        except Exception as e:
            return {
                "content": "",
                "file_path": str(file_path),
                "line_count": 0,
                "encoding": "utf-8",
                "error": f"Error reading file: {str(e)}"
            }

