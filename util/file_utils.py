"""代码审查系统的文件读取工具。"""

import logging
from pathlib import Path
from typing import Optional

from core.config import Config

logger = logging.getLogger(__name__)


def read_file_content(file_path: str, config: Optional[Config] = None) -> str:
    """读取文件的完整内容。
    
    Args:
        file_path: 文件路径（相对于仓库根目录或绝对路径）。
        config: 包含 workspace_root 的配置对象。如果为 None，将尝试使用当前工作目录。
    
    Returns:
        文件内容字符串，如果无法读取则返回空字符串。
    """
    try:
        if not config or not hasattr(config, 'system') or not hasattr(config.system, 'workspace_root'):
            logger.warning(f"Cannot read file content: config or workspace_root not available")
            # Fallback to current working directory
            workspace_root = Path.cwd()
        else:
            workspace_root = config.system.workspace_root
        
        file_path_obj = Path(file_path)
        
        if not file_path_obj.is_absolute():
            # Resolve relative to workspace root
            file_path_obj = Path(workspace_root) / file_path_obj
        else:
            file_path_obj = Path(file_path)
        
        if not file_path_obj.exists():
            logger.warning(f"File not found: {file_path_obj}")
            return ""
        
        with open(file_path_obj, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.warning(f"Error reading file content for {file_path}: {e}")
        return ""

