"""语法检查器基类。

定义所有语法检查器必须实现的抽象接口。
语法检查器在基于 AI 的代码审查之前提供确定性静态分析。
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List

from pydantic import BaseModel, Field


class LintError(BaseModel):
    """单个 lint 错误。"""
    
    file: str = Field(..., description="File path relative to repository root")
    line: int = Field(..., description="Line number (1-indexed)")
    message: str = Field(..., description="Error message")
    severity: str = Field(default="error", description="Severity: error, warning, or info")
    code: str = Field(default="", description="Optional error code (e.g., 'E501', 'F401')")
    
    class Config:
        """Pydantic 配置。"""
        frozen = True


class BaseSyntaxChecker(ABC):
    """所有语法检查器的抽象基类。
    
    所有语法检查器必须继承此类并实现 `check` 方法。
    检查器负责在文件列表上运行静态分析工具（如 ruff、eslint），
    并返回标准化的错误报告。
    """
    
    @abstractmethod
    async def check(
        self,
        repo_path: Path,
        files: List[str]
    ) -> List[LintError]:
        """对指定文件运行语法/lint 检查。
        
        Returns:
            LintError 对象列表。如果未找到错误或检查器不可用，返回空列表。
        
        Note:
            此方法应优雅处理以下情况：
            - 检查器工具未安装（返回空列表）
            - 文件不存在（跳过）
            - 检查器失败（返回空列表或部分结果）
        """
        pass
    
    @abstractmethod
    def get_supported_extensions(self) -> List[str]:
        """获取此检查器支持的文件扩展名列表。"""
        pass
    
    def _filter_existing_files(
        self,
        repo_path: Path,
        files: List[str]
    ) -> List[Path]:
        """过滤文件列表，仅包含存在的文件。"""
        existing = []
        for file_path in files:
            full_path = repo_path / file_path
            if full_path.exists() and full_path.is_file():
                existing.append(full_path)
        return existing
