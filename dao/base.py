"""存储后端基类。

定义所有存储后端必须实现的抽象接口。
支持未来迁移到 SQL、NoSQL 或 GraphDB。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseStorageBackend(ABC):
    """所有存储后端的抽象基类。
    
    设计支持：
    - Collections：数据逻辑分组（如 "assets", "reviews", "cache"）
    - Keys：集合内的唯一标识符
    - Data：JSON 可序列化对象或二进制数据
    """
    
    @abstractmethod
    async def connect(self) -> None:
        """初始化存储后端连接（幂等操作）。
        
        Raises:
            Exception: 连接失败。
        """
        pass
    
    @abstractmethod
    async def save(self, collection: str, key: str, data: Any) -> None:
        """保存数据到存储后端。
        
        Raises:
            Exception: 保存失败。
        """
        pass
    
    @abstractmethod
    async def load(self, collection: str, key: str) -> Optional[Any]:
        """从存储后端加载数据。
        
        Returns:
            加载的数据，不存在则返回 None。
        
        Raises:
            Exception: 加载失败（键不存在除外）。
        """
        pass
    
    @abstractmethod
    async def exists(self, collection: str, key: str) -> bool:
        """检查键是否存在。"""
        pass
    
    @abstractmethod
    async def delete(self, collection: str, key: str) -> None:
        """从存储后端删除数据。
        
        Raises:
            Exception: 删除失败。
        """
        pass
