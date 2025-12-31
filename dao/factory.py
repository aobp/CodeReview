"""创建和管理存储后端实例的工厂。

提供存储后端的单例工厂模式，确保每种后端类型只创建一个实例并重复使用。
"""

from typing import Optional
from pathlib import Path
from dao.base import BaseStorageBackend
from dao.backends.local_file import LocalFileBackend


class StorageFactory:
    """创建存储后端实例的工厂类。
    
    此类维护存储后端的单例实例，以确保高效的资源使用和应用程序中的一致状态。
    """
    
    _instances: dict[str, BaseStorageBackend] = {}
    _default_type: str = "local"
    
    @classmethod
    def get_storage(
        cls,
        storage_type: str = "local",
        **kwargs
    ) -> BaseStorageBackend:
        """获取存储后端实例。
        
        此方法返回指定存储后端的单例实例。如果实例不存在，则创建新实例。
        
        Raises:
            ValueError: 存储类型不支持。
        """
        # Use default type if not specified
        if not storage_type:
            storage_type = cls._default_type
        
        # Return existing instance if available
        if storage_type in cls._instances:
            return cls._instances[storage_type]
        
        # Create new instance based on type
        if storage_type == "local":
            storage_root = kwargs.get("storage_root")
            instance = LocalFileBackend(storage_root=storage_root)
        else:
            raise ValueError(
                f"Unsupported storage type: {storage_type}. "
                f"Supported types: local (SQL/NoSQL backends coming soon)"
            )
        
        # Store and return instance
        cls._instances[storage_type] = instance
        return instance
    
    @classmethod
    def set_default_type(cls, storage_type: str) -> None:
        """设置默认存储类型。"""
        cls._default_type = storage_type
    
    @classmethod
    def reset(cls) -> None:
        """重置所有存储实例（用于测试）。"""
        cls._instances.clear()


def get_storage(storage_type: str = "local", **kwargs) -> BaseStorageBackend:
    """便捷函数，获取存储后端实例。"""
    return StorageFactory.get_storage(storage_type, **kwargs)
