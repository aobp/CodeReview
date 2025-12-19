"""Base classes for syntax checkers.

This module defines the abstract interface that all syntax checkers must implement.
Syntax checkers provide deterministic static analysis before AI-based code review.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List

from pydantic import BaseModel, Field


class LintError(BaseModel):
    """Represents a single linting error.
    
    Attributes:
        file: Path to the file with the error (relative to repo root).
        line: Line number where the error occurs (1-indexed).
        message: Error message describing the issue.
        severity: Severity level ("error", "warning", or "info").
        code: Optional error code (e.g., "E501", "F401" for Ruff).
    """
    
    file: str = Field(..., description="File path relative to repository root")
    line: int = Field(..., description="Line number (1-indexed)")
    message: str = Field(..., description="Error message")
    severity: str = Field(default="error", description="Severity: error, warning, or info")
    code: str = Field(default="", description="Optional error code (e.g., 'E501', 'F401')")
    
    class Config:
        """Pydantic configuration."""
        frozen = True


class BaseSyntaxChecker(ABC):
    """Abstract base class for all syntax checkers.
    
    All syntax checkers must inherit from this class and implement the `check` method.
    Checkers are responsible for running static analysis tools (e.g., ruff, eslint)
    on a list of files and returning standardized error reports.
    """
    
    @abstractmethod
    async def check(
        self,
        repo_path: Path,
        files: List[str]
    ) -> List[LintError]:
        """Run syntax/lint checking on the specified files.
        
        Args:
            repo_path: Root path of the repository.
            files: List of file paths relative to repo_path to check.
        
        Returns:
            A list of LintError objects found in the files. Returns empty list
            if no errors found or if checker is not available.
        
        Note:
            This method should gracefully handle cases where:
            - The checker tool is not installed (return empty list)
            - Files don't exist (skip them)
            - The checker fails (return empty list or partial results)
        """
        pass
    
    @abstractmethod
    def get_supported_extensions(self) -> List[str]:
        """Get list of file extensions this checker supports.
        
        Returns:
            List of file extensions (e.g., [".py", ".pyi"] for Python).
        """
        pass
    
    def _filter_existing_files(
        self,
        repo_path: Path,
        files: List[str]
    ) -> List[Path]:
        """Filter files list to only include files that exist.
        
        Args:
            repo_path: Root path of the repository.
            files: List of file paths relative to repo_path.
        
        Returns:
            List of Path objects for files that exist.
        """
        existing = []
        for file_path in files:
            full_path = repo_path / file_path
            if full_path.exists() and full_path.is_file():
                existing.append(full_path)
        return existing
