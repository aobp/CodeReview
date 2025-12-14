"""Asset registry for managing asset builders.

This module provides a registry pattern for registering and retrieving
asset builders by their type.
"""

from typing import Dict, Type, Optional
from assets.base import BaseAssetBuilder


class AssetRegistry:
    """Registry for asset builders.
    
    This class maintains a mapping of asset types to their builder classes,
    allowing dynamic registration and retrieval of asset builders.
    
    Attributes:
        _builders: Dictionary mapping asset type strings to builder classes.
    """
    
    def __init__(self):
        """Initialize an empty registry."""
        self._builders: Dict[str, Type[BaseAssetBuilder]] = {}
    
    def register(self, asset_type: str, builder_class: Type[BaseAssetBuilder]) -> None:
        """Register an asset builder class.
        
        Args:
            asset_type: The unique identifier for the asset type.
            builder_class: The builder class that implements BaseAssetBuilder.
        
        Raises:
            ValueError: If the asset_type is already registered.
        """
        if asset_type in self._builders:
            raise ValueError(f"Asset type '{asset_type}' is already registered")
        self._builders[asset_type] = builder_class
    
    def get(self, asset_type: str) -> Optional[Type[BaseAssetBuilder]]:
        """Get an asset builder class by type.
        
        Args:
            asset_type: The unique identifier for the asset type.
        
        Returns:
            The builder class if found, None otherwise.
        """
        return self._builders.get(asset_type)
    
    def create(self, asset_type: str, **kwargs) -> Optional[BaseAssetBuilder]:
        """Create an instance of an asset builder.
        
        Args:
            asset_type: The unique identifier for the asset type.
            **kwargs: Arguments to pass to the builder constructor.
        
        Returns:
            An instance of the builder if found, None otherwise.
        
        Raises:
            ValueError: If the asset_type is not registered.
        """
        builder_class = self.get(asset_type)
        if builder_class is None:
            raise ValueError(f"Asset type '{asset_type}' is not registered")
        return builder_class(asset_type=asset_type, **kwargs)


# Global registry instance
_registry = AssetRegistry()


def get_registry() -> AssetRegistry:
    """Get the global asset registry instance.
    
    Returns:
        The global AssetRegistry instance.
    """
    return _registry

