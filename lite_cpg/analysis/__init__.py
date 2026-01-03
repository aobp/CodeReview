"""Code analysis tools and algorithms.

This module provides various static analysis tools for code understanding,
including program slicing, taint analysis, and source/sink detection.
"""

def __getattr__(name):
    """Lazy import to avoid circular dependencies."""

    if name in ("backward_slice", "forward_slice"):
        from .slicer import backward_slice, forward_slice
        return locals()[name]

    if name in ("forward_taint_paths_store", "backward_taint_paths_store", "TaintOptions"):
        from .taint import forward_taint_paths_store, backward_taint_paths_store, TaintOptions
        return locals()[name]

    if name in ("SourceSinkConfig", "DEFAULT_SOURCE_SINK_CONFIG"):
        from .source_sink import SourceSinkConfig, DEFAULT_SOURCE_SINK_CONFIG
        return locals()[name]

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = [
    "backward_slice",
    "forward_slice",
    "forward_taint_paths_store",
    "backward_taint_paths_store",
    "TaintOptions",
    "SourceSinkConfig",
    "DEFAULT_SOURCE_SINK_CONFIG",
]
