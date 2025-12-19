"""Syntax checking tools for various programming languages."""

from external_tools.syntax_checker.base import BaseSyntaxChecker, LintError
from external_tools.syntax_checker.factory import CheckerFactory

# Register checkers
from external_tools.syntax_checker.implementations.python_ruff import PythonRuffChecker

# Auto-register Python Ruff checker
CheckerFactory.register(PythonRuffChecker, [".py", ".pyi"])

__all__ = ["BaseSyntaxChecker", "CheckerFactory", "LintError"]
