"""Base classes for asset builders.

This module defines the abstract interface that all asset builders must implement.
Assets represent analyzed code structures such as ASTs, RepoMaps, and CPGs.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pathlib import Path


class BaseAssetBuilder(ABC):
    """Abstract base class for all asset builders.
    
    All asset builders (e.g., RepoMapBuilder, CPGBuilder) must inherit from this
    class and implement the four core methods: build, query, save, and load.
    
    Attributes:
        asset_type: A string identifier for the type of asset (e.g., "repo_map", "cpg").
    """
    
    def __init__(self, asset_type: str):
        """Initialize the asset builder.
        
        Args:
            asset_type: A unique identifier for this asset type.
        """
        self.asset_type = asset_type
    
    @abstractmethod
    async def build(self, source_path: Path, **kwargs: Any) -> Dict[str, Any]:
        """Build the asset from source code.
        
        This method should analyze the codebase at the given path and generate
        the asset representation. For MVP, this can be a simplified version.
        
        Args:
            source_path: Path to the source code directory or file.
            **kwargs: Additional parameters specific to the asset builder.
        
        Returns:
            A dictionary containing the built asset data. The structure is
            asset-specific but must be JSON-serializable.
        
        Raises:
            Exception: If the build process fails.
        """
        pass
    
    @abstractmethod
    async def query(self, query: str, **kwargs: Any) -> Dict[str, Any]:
        """Query the asset with a natural language or structured query.
        
        Args:
            query: The query string (e.g., "find all functions in file X").
            **kwargs: Additional query parameters.
        
        Returns:
            A dictionary containing query results. Must be JSON-serializable.
        
        Raises:
            Exception: If the query fails.
        """
        pass
    
    @abstractmethod
    async def save(self, output_path: Path, asset_data: Dict[str, Any]) -> None:
        """Save the asset to disk.
        
        Args:
            output_path: Path where the asset should be saved.
            asset_data: The asset data dictionary to save.
        
        Raises:
            Exception: If the save operation fails.
        """
        pass
    
    @abstractmethod
    async def load(self, input_path: Path) -> Dict[str, Any]:
        """Load the asset from disk.
        
        Args:
            input_path: Path to the saved asset file.
        
        Returns:
            A dictionary containing the loaded asset data.
        
        Raises:
            Exception: If the load operation fails or the file doesn't exist.
        """
        pass

