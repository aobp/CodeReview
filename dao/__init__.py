"""DAO (Data Access Object) layer for extensible storage backends.

This module provides a unified interface for storing and retrieving data,
with support for multiple backend implementations (file, SQL, NoSQL, etc.).
"""

from dao.base import BaseStorageBackend
from dao.factory import get_storage, StorageFactory

__all__ = ["BaseStorageBackend", "get_storage", "StorageFactory"]
