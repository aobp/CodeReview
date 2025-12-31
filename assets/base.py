"""资产构建器基类。

定义所有资产构建器必须实现的抽象接口。
资产表示分析的代码结构（如 AST、RepoMap、CPG）。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pathlib import Path


class BaseAssetBuilder(ABC):
    """所有资产构建器的抽象基类。"""
    
    def __init__(self, asset_type: str):
        """初始化资产构建器。"""
        self.asset_type = asset_type
    
    @abstractmethod
    async def build(self, source_path: Path, **kwargs: Any) -> Dict[str, Any]:
        """从源代码构建资产。
        
        Returns:
            JSON 可序列化的资产数据字典。
        
        Raises:
            Exception: 构建失败。
        """
        pass
    
    @abstractmethod
    async def query(self, query: str, **kwargs: Any) -> Dict[str, Any]:
        """查询资产（自然语言或结构化查询）。
        
        Returns:
            JSON 可序列化的查询结果字典。
        
        Raises:
            Exception: 查询失败。
        """
        pass
    
    @abstractmethod
    async def save(self, output_path: Path, asset_data: Dict[str, Any]) -> None:
        """保存资产到磁盘。
        
        Raises:
            Exception: 保存失败。
        """
        pass
    
    @abstractmethod
    async def load(self, input_path: Path) -> Dict[str, Any]:
        """从磁盘加载资产。
        
        Returns:
            资产数据字典。
        
        Raises:
            Exception: 加载失败或文件不存在。
        """
        pass

