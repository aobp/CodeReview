"""代码审查系统的文件读取工具。"""

from pathlib import Path
from typing import Any, Dict, Optional
from pydantic import Field
from tools.base import BaseTool


class ReadFileTool(BaseTool):
    """文件读取工具。"""
    
    workspace_root: Optional[Path] = Field(
        default=None,
        description="Root path of the workspace. If None, uses current working directory."
    )
    
    def __init__(self, workspace_root: Optional[Path] = None, **kwargs):
        """初始化文件读取工具。"""
        if workspace_root is None:
            workspace_root = Path.cwd()
        super().__init__(
            name="read_file",
            description="Read the contents of a file from the codebase",
            workspace_root=workspace_root,
            **kwargs
        )
    
    async def run(self, file_path: str, **kwargs: Any) -> Dict[str, Any]:
        """读取文件并返回内容。
        
        Returns:
            包含 "content" 和 "file_path" 的字典。
                - "line_count": Number of lines in the file.
                - "encoding": The encoding used.
                - "error": Optional error message if reading failed.
        """
        try:
            file_path_obj = Path(file_path)
            if not file_path_obj.is_absolute():
                # Resolve relative to workspace root
                workspace = self.workspace_root if self.workspace_root else Path.cwd()
                file_path_obj = workspace / file_path_obj
            
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

