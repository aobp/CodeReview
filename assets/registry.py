"""资产构建器注册表。

提供注册表模式，用于按类型注册和检索资产构建器。
"""

from typing import Dict, Type, Optional
from assets.base import BaseAssetBuilder


class AssetRegistry:
    """资产构建器注册表。
    
    此类维护资产类型到其构建器类的映射，
    允许动态注册和检索资产构建器。
    """
    
    def __init__(self):
        """初始化空注册表。"""
        self._builders: Dict[str, Type[BaseAssetBuilder]] = {}
    
    def register(self, asset_type: str, builder_class: Type[BaseAssetBuilder]) -> None:
        """注册资产构建器类。
        
        Raises:
            ValueError: 资产类型已注册。
        """
        if asset_type in self._builders:
            raise ValueError(f"Asset type '{asset_type}' is already registered")
        self._builders[asset_type] = builder_class
    
    def get(self, asset_type: str) -> Optional[Type[BaseAssetBuilder]]:
        """按类型获取资产构建器类。"""
        return self._builders.get(asset_type)
    
    def create(self, asset_type: str, **kwargs) -> Optional[BaseAssetBuilder]:
        """创建资产构建器实例。
        
        Raises:
            ValueError: 资产类型未注册。
        """
        builder_class = self.get(asset_type)
        if builder_class is None:
            raise ValueError(f"Asset type '{asset_type}' is not registered")
        return builder_class(asset_type=asset_type, **kwargs)


# 全局注册表实例
_registry = AssetRegistry()


def get_registry() -> AssetRegistry:
    """获取全局资产注册表实例。"""
    return _registry

