"""Base classes for storage backends.

This module defines the abstract interface that all storage backends must implement.
Storage backends provide a unified interface for persisting and retrieving data,
supporting future migration to SQL, NoSQL, or GraphDB implementations.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseStorageBackend(ABC):
    """Abstract base class for all storage backends.
    
    All storage backends (e.g., LocalFileBackend, SQLBackend, MongoDBBackend)
    must inherit from this class and implement the core methods: connect, save, and load.
    
    The design supports:
    - Collections: Logical groupings of data (e.g., "assets", "reviews", "cache")
    - Keys: Unique identifiers within a collection
    - Data: JSON-serializable objects or binary data
    """
    
    @abstractmethod
    async def connect(self) -> None:
        """Initialize the storage backend connection.
        
        This method should establish any necessary connections, create directories,
        or initialize database schemas. It should be idempotent (safe to call multiple times).
        
        Raises:
            Exception: If the connection cannot be established.
        """
        pass
    
    @abstractmethod
    async def save(self, collection: str, key: str, data: Any) -> None:
        """Save data to the storage backend.
        
        Args:
            collection: The collection name (e.g., "assets", "reviews").
            key: Unique identifier within the collection.
            data: The data to save. Can be a dict, list, or any JSON-serializable object.
                 For binary data, backends should handle encoding appropriately.
        
        Raises:
            Exception: If the save operation fails.
        """
        pass
    
    @abstractmethod
    async def load(self, collection: str, key: str) -> Optional[Any]:
        """Load data from the storage backend.
        
        Args:
            collection: The collection name.
            key: Unique identifier within the collection.
        
        Returns:
            The loaded data, or None if the key doesn't exist.
        
        Raises:
            Exception: If the load operation fails (other than key not found).
        """
        pass
    
    @abstractmethod
    async def exists(self, collection: str, key: str) -> bool:
        """Check if a key exists in a collection.
        
        Args:
            collection: The collection name.
            key: Unique identifier within the collection.
        
        Returns:
            True if the key exists, False otherwise.
        """
        pass
    
    @abstractmethod
    async def delete(self, collection: str, key: str) -> None:
        """Delete data from the storage backend.
        
        Args:
            collection: The collection name.
            key: Unique identifier within the collection.
        
        Raises:
            Exception: If the delete operation fails.
        """
        pass
