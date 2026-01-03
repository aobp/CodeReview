"""Storage layer for Lite CPG.

This module provides persistent storage capabilities for code analysis data,
including CPG graphs, repository indexes, and analysis results.
"""

def __getattr__(name):
    """Lazy import to avoid circular dependencies."""

    if name == "LiteCPGStore":
        from .base import LiteCPGStore
        return LiteCPGStore

    if name in ("index_repository", "default_store_paths", "StorePaths"):
        from .backends.sqlite import index_repository, default_store_paths, StorePaths
        return locals()[name]

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = [
    "LiteCPGStore",
    "index_repository",
    "default_store_paths",
    "StorePaths",
]
