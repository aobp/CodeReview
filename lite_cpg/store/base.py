"""Base storage interface for Lite CPG.

This module defines the abstract base class for all storage backends,
providing a consistent interface for persisting and retrieving code analysis data.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path


class LiteCPGStore(ABC):
    """Abstract base class for Lite CPG storage backends.

    This interface defines the contract that all storage implementations must follow,
    supporting both in-memory and persistent storage strategies.
    """

    @abstractmethod
    def connect(self) -> None:
        """Initialize the storage connection.

        This method should establish any necessary connections, create tables/schemas,
        or perform other initialization required for the storage backend.

        Raises:
            Exception: If connection initialization fails.
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the storage connection.

        This method should cleanly close any open connections and release resources.
        """
        pass

    @abstractmethod
    def store_blob(self, path: Path, content: bytes, lang: str) -> int:
        """Store a file blob and return its ID.

        Args:
            path: File path.
            content: File content as bytes.
            lang: Programming language.

        Returns:
            The blob ID for the stored content.

        Raises:
            Exception: If storage fails.
        """
        pass

    @abstractmethod
    def get_blob(self, blob_id: int) -> Optional[Tuple[Path, bytes, str]]:
        """Retrieve a stored blob by ID.

        Args:
            blob_id: The blob ID to retrieve.

        Returns:
            Tuple of (path, content, lang) if found, None otherwise.
        """
        pass

    @abstractmethod
    def store_cpg(self, file_id: int, cpg_data: Dict[str, Any]) -> None:
        """Store CPG data for a file.

        Args:
            file_id: File identifier.
            cpg_data: CPG data as a dictionary.

        Raises:
            Exception: If storage fails.
        """
        pass

    @abstractmethod
    def get_cpg(self, file_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve CPG data for a file.

        Args:
            file_id: File identifier.

        Returns:
            CPG data dictionary if found, None otherwise.
        """
        pass

    @abstractmethod
    def store_repomap(self, file_id: int, repomap_data: Dict[str, Any]) -> None:
        """Store repository map data for a file.

        Args:
            file_id: File identifier.
            repomap_data: Repository map data.

        Raises:
            Exception: If storage fails.
        """
        pass

    @abstractmethod
    def get_repomap(self, file_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve repository map data for a file.

        Args:
            file_id: File identifier.

        Returns:
            Repository map data if found, None otherwise.
        """
        pass

    @abstractmethod
    def list_files(self, repo_root: Optional[Path] = None) -> List[Tuple[int, Path, str]]:
        """List all stored files.

        Args:
            repo_root: Optional repository root to filter by.

        Returns:
            List of (file_id, path, lang) tuples.
        """
        pass
