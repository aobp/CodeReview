"""Base classes for MCP-compliant tools.

This module defines the base tool interface that all tools must implement.
Tools wrap asset queries and provide a standardized interface for agents.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict
from pydantic import BaseModel, Field


class BaseTool(BaseModel, ABC):
    """Base class for all MCP-compliant tools.
    
    All tools must inherit from this class and implement the `run` method.
    Tools are Pydantic models, ensuring type safety and validation.
    
    Attributes:
        name: The name of the tool (e.g., "read_file", "search_repo").
        description: A human-readable description of what the tool does.
    """
    
    name: str = Field(..., description="The name of the tool")
    description: str = Field(..., description="Human-readable description of the tool")
    
    @abstractmethod
    async def run(self, **kwargs: Any) -> Dict[str, Any]:
        """Execute the tool with the given parameters.
        
        Args:
            **kwargs: Tool-specific parameters. Each tool should define its
                     expected parameters in its docstring or schema.
        
        Returns:
            A dictionary containing the tool's output. Must be JSON-serializable.
            The structure should be consistent for the same tool type.
        
        Raises:
            Exception: If the tool execution fails. Tools should handle errors
                     gracefully and return error information in the result dict.
        """
        pass
    
    class Config:
        """Pydantic configuration."""
        arbitrary_types_allowed = True

