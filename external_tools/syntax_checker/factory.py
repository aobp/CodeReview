"""Factory for creating syntax checkers based on file extensions."""

from pathlib import Path
from typing import Dict, List, Optional

from external_tools.syntax_checker.base import BaseSyntaxChecker


class CheckerFactory:
    """Factory class for selecting and creating appropriate syntax checkers.
    
    This factory maintains a registry of checkers and selects the appropriate
    checker based on file extensions. It supports multiple checkers for the same
    language (e.g., ruff and pylint for Python).
    """
    
    _checkers: Dict[str, type[BaseSyntaxChecker]] = {}
    _extension_map: Dict[str, type[BaseSyntaxChecker]] = {}
    
    @classmethod
    def register(
        cls,
        checker_class: type[BaseSyntaxChecker],
        extensions: List[str]
    ) -> None:
        """Register a syntax checker for specific file extensions.
        
        Args:
            checker_class: The checker class to register.
            extensions: List of file extensions (e.g., [".py", ".pyi"]).
        """
        cls._checkers[checker_class.__name__] = checker_class
        for ext in extensions:
            # Normalize extension (ensure it starts with .)
            ext = ext if ext.startswith(".") else f".{ext}"
            # If multiple checkers for same extension, last one wins
            # (could be enhanced to support multiple checkers per extension)
            cls._extension_map[ext.lower()] = checker_class
    
    @classmethod
    def get_checker_for_file(
        cls,
        file_path: str
    ) -> Optional[type[BaseSyntaxChecker]]:
        """Get the appropriate checker class for a file.
        
        Args:
            file_path: Path to the file (can be relative or absolute).
        
        Returns:
            The checker class for this file, or None if no checker is registered.
        """
        path = Path(file_path)
        ext = path.suffix.lower()
        return cls._extension_map.get(ext)
    
    @classmethod
    def get_checkers_for_files(
        cls,
        files: List[str]
    ) -> Dict[type[BaseSyntaxChecker], List[str]]:
        """Group files by their appropriate checker.
        
        Args:
            files: List of file paths to check.
        
        Returns:
            Dictionary mapping checker classes to lists of files they should check.
        """
        grouped: Dict[type[BaseSyntaxChecker], List[str]] = {}
        
        for file_path in files:
            checker_class = cls.get_checker_for_file(file_path)
            if checker_class:
                if checker_class not in grouped:
                    grouped[checker_class] = []
                grouped[checker_class].append(file_path)
        
        return grouped
    
    @classmethod
    def get_all_checkers(cls) -> Dict[str, type[BaseSyntaxChecker]]:
        """Get all registered checkers.
        
        Returns:
            Dictionary mapping checker names to checker classes.
        """
        return cls._checkers.copy()
