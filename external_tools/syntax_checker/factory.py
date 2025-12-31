"""基于文件扩展名创建语法检查器的工厂。"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from external_tools.syntax_checker.base import BaseSyntaxChecker


class CheckerFactory:
    """选择和创建适当语法检查器的工厂类。
    
    此工厂维护检查器注册表，并根据文件扩展名选择适当的检查器。
    支持同一语言的多个检查器（如 Python 的 ruff 和 pylint）。
    """
    
    _checkers: Dict[str, type[BaseSyntaxChecker]] = {}
    _extension_map: Dict[str, List[type[BaseSyntaxChecker]]] = {}
    
    @classmethod
    def register(
        cls,
        checker_class: type[BaseSyntaxChecker],
        extensions: List[str]
    ) -> None:
        """为特定文件扩展名注册语法检查器。"""
        cls._checkers[checker_class.__name__] = checker_class
        for ext in extensions:
            # Normalize extension (ensure it starts with .)
            ext = ext if ext.startswith(".") else f".{ext}"
            ext_lower = ext.lower()
            # Support multiple checkers per extension
            if ext_lower not in cls._extension_map:
                cls._extension_map[ext_lower] = []
            if checker_class not in cls._extension_map[ext_lower]:
                cls._extension_map[ext_lower].append(checker_class)
    
    @classmethod
    def get_checkers_for_file(
        cls,
        file_path: str
    ) -> List[type[BaseSyntaxChecker]]:
        """获取文件的所有适当检查器类。
        
        Returns:
            此文件的检查器类列表。如果未注册检查器，返回空列表。
        """
        path = Path(file_path)
        ext = path.suffix.lower()
        return cls._extension_map.get(ext, [])
    
    @classmethod
    def get_checker_for_file(
        cls,
        file_path: str
    ) -> Optional[type[BaseSyntaxChecker]]:
        """获取文件的第一个适当检查器类（向后兼容）。"""
        checkers = cls.get_checkers_for_file(file_path)
        return checkers[0] if checkers else None
    
    @classmethod
    def get_checkers_for_files(
        cls,
        files: List[str]
    ) -> Dict[type[BaseSyntaxChecker], List[str]]:
        """按适当的检查器对文件进行分组。
        
        Returns:
            将检查器类映射到应检查的文件列表的字典。
            如果为同一扩展名注册了多个检查器，多个检查器可以检查同一文件。
        """
        grouped: Dict[type[BaseSyntaxChecker], List[str]] = {}
        
        for file_path in files:
            checker_classes = cls.get_checkers_for_file(file_path)
            for checker_class in checker_classes:
                if checker_class not in grouped:
                    grouped[checker_class] = []
                grouped[checker_class].append(file_path)
        
        return grouped
    
    @classmethod
    def get_all_checkers(cls) -> Dict[str, type[BaseSyntaxChecker]]:
        """获取所有已注册的检查器。"""
        return cls._checkers.copy()
