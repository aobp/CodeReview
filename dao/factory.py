"""Factory for creating and managing storage backend instances.

This module provides a singleton factory pattern for storage backends,
ensuring that only one instance of each backend type is created and reused.
"""

from typing import Optional
from pathlib import Path
from dao.base import BaseStorageBackend
from dao.backends.local_file import LocalFileBackend


class StorageFactory:
    """Factory for creating storage backend instances.
    
    This class maintains singleton instances of storage backends to ensure
    efficient resource usage and consistent state across the application.
    """
    
    _instances: dict[str, BaseStorageBackend] = {}
    _default_type: str = "local"
    
    @classmethod
    def get_storage(
        cls,
        storage_type: str = "local",
        **kwargs
    ) -> BaseStorageBackend:
        """Get a storage backend instance.
        
        This method returns a singleton instance of the specified storage backend.
        If the instance doesn't exist, it creates a new one.
        
        Args:
            storage_type: Type of storage backend ("local", "sql", "mongodb", etc.).
                         Defaults to "local".
            **kwargs: Additional parameters for backend initialization.
                     For "local": storage_root (Path, optional)
        
        Returns:
            A BaseStorageBackend instance.
        
        Raises:
            ValueError: If the storage type is not supported.
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
        """Set the default storage type.
        
        Args:
            storage_type: The default storage type to use.
        """
        cls._default_type = storage_type
    
    @classmethod
    def reset(cls) -> None:
        """Reset all storage instances (useful for testing)."""
        cls._instances.clear()


# Convenience function for easy access
def get_storage(storage_type: str = "local", **kwargs) -> BaseStorageBackend:
    """Convenience function to get a storage backend instance.
    
    Args:
        storage_type: Type of storage backend (defaults to "local").
        **kwargs: Additional parameters for backend initialization.
    
    Returns:
        A BaseStorageBackend instance.
    """
    return StorageFactory.get_storage(storage_type, **kwargs)
