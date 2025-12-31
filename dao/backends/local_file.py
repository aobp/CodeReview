"""基于本地文件的存储后端实现。

实现基于文件的存储后端，将数据保存为 JSON 文件，
目录结构：.storage/{collection}/{key}.json
"""

import json
from pathlib import Path
from typing import Any, Optional
from dao.base import BaseStorageBackend


class LocalFileBackend(BaseStorageBackend):
    """使用本地文件系统的基于文件的存储后端。
    
    数据以 JSON 文件形式存储，结构：.storage/{collection}/{key}.json
    
    此后端适用于 MVP 和开发，在生产环境中可以轻松替换为数据库后端。
    """
    
    def __init__(self, storage_root: Path = None):
        """初始化 LocalFileBackend。"""
        if storage_root is None:
            storage_root = Path.cwd() / ".storage"
        self.storage_root = Path(storage_root).resolve()
        self._connected = False
    
    async def connect(self) -> None:
        """初始化存储目录（幂等操作）。"""
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._connected = True
    
    def _get_file_path(self, collection: str, key: str) -> Path:
        """获取集合和键的文件路径。"""
        # Sanitize collection and key to avoid path traversal
        collection = collection.replace("/", "_").replace("..", "")
        key = key.replace("/", "_").replace("..", "")
        
        collection_dir = self.storage_root / collection
        return collection_dir / f"{key}.json"
    
    async def save(self, collection: str, key: str, data: Any) -> None:
        """将数据保存到 JSON 文件。
        
        Raises:
            Exception: 保存操作失败（如权限错误、序列化错误）。
        """
        if not self._connected:
            await self.connect()
        
        file_path = self._get_file_path(collection, key)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Data is not JSON-serializable: {str(e)}")
        except IOError as e:
            raise IOError(f"Failed to save data to {file_path}: {str(e)}")
    
    async def load(self, collection: str, key: str) -> Optional[Any]:
        """Load data from a JSON file.
        
        Args:
            collection: The collection name.
            key: Unique identifier within the collection.
        
        Returns:
            The loaded data, or None if the file doesn't exist.
        
        Raises:
            Exception: If the load operation fails (e.g., invalid JSON, permission error).
        """
        if not self._connected:
            await self.connect()
        
        file_path = self._get_file_path(collection, key)
        
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {file_path}: {str(e)}")
        except IOError as e:
            raise IOError(f"Failed to load data from {file_path}: {str(e)}")
    
    async def exists(self, collection: str, key: str) -> bool:
        """Check if a key exists in a collection.
        
        Args:
            collection: The collection name.
            key: Unique identifier within the collection.
        
        Returns:
            True if the file exists, False otherwise.
        """
        if not self._connected:
            await self.connect()
        
        file_path = self._get_file_path(collection, key)
        return file_path.exists()
    
    async def delete(self, collection: str, key: str) -> None:
        """Delete a file from storage.
        
        Args:
            collection: The collection name.
            key: Unique identifier within the collection.
        
        Raises:
            Exception: If the delete operation fails (e.g., permission error).
        """
        if not self._connected:
            await self.connect()
        
        file_path = self._get_file_path(collection, key)
        
        if file_path.exists():
            try:
                file_path.unlink()
            except IOError as e:
                raise IOError(f"Failed to delete {file_path}: {str(e)}")
