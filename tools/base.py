"""MCP 兼容工具基类。

定义所有工具必须实现的基类接口。
工具封装资产查询，为智能体提供标准化接口。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict
from pydantic import BaseModel, Field


class BaseTool(BaseModel, ABC):
    """所有 MCP 兼容工具的基类。
    
    所有工具必须继承此类并实现 `run` 方法。
    工具是 Pydantic 模型，确保类型安全和验证。
    """
    
    name: str = Field(..., description="The name of the tool")
    description: str = Field(..., description="Human-readable description of the tool")
    
    @abstractmethod
    async def run(self, **kwargs: Any) -> Dict[str, Any]:
        """执行工具。
        
        Returns:
            JSON 可序列化的输出字典。
        
        Raises:
            Exception: 工具执行失败。
        """
        pass
    
    class Config:
        """Pydantic 配置。"""
        arbitrary_types_allowed = True

