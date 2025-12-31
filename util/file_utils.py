"""File reading utilities for the code review system.

This module provides utilities for reading file contents from the workspace.
"""

import logging
from pathlib import Path
from typing import Optional

from core.config import Config

logger = logging.getLogger(__name__)


def read_file_content(file_path: str, config: Optional[Config] = None) -> str:
    """Read the full content of a file.
    
    Args:
        file_path: Path to the file (relative to repo root or absolute).
        config: Config object containing workspace_root. If None, will try to use
                current working directory as workspace root.
    
    Returns:
        File content as string, or empty string if file cannot be read.
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

