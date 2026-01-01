"""Syntax checking tools for various programming languages."""

from external_tools.syntax_checker.base import BaseSyntaxChecker, LintError
from external_tools.syntax_checker.factory import CheckerFactory
from external_tools.syntax_checker.config_loader import get_config

# Import all available checkers
from external_tools.syntax_checker.implementations.python_ruff import PythonRuffChecker
from external_tools.syntax_checker.implementations.typescript_biome import TypeScriptBiomeChecker
from external_tools.syntax_checker.implementations.go_vet import GoVetChecker
from external_tools.syntax_checker.implementations.java_pmd import JavaPMDChecker

# Load configuration
_config = get_config()

# Register checkers based on configuration
# Python checkers
if _config.is_checker_enabled("python", "ruff"):
    CheckerFactory.register(PythonRuffChecker, [".py", ".pyi"])

# TypeScript/JavaScript checkers (using Biome, replacing ESLint)
if _config.is_checker_enabled("typescript", "biome"):
    CheckerFactory.register(TypeScriptBiomeChecker, [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"])

# Go checkers (using go vet, official Go tool)
if _config.is_checker_enabled("go", "vet"):
    CheckerFactory.register(GoVetChecker, [".go"])

# Java checkers
if _config.is_checker_enabled("java", "pmd"):
    CheckerFactory.register(JavaPMDChecker, [".java"])

__all__ = ["BaseSyntaxChecker", "CheckerFactory", "LintError", "get_config"]
