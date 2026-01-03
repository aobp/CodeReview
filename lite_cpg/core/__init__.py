"""Core data structures and builders for Lite CPG.

This module contains the fundamental components for building and representing
code property graphs, including AST parsing, CFG construction, and symbol indexing.
"""

def __getattr__(name):
    """Lazy import to avoid circular dependencies."""

    # Core data structures
    if name in ("LiteCPG", "Node", "Edge", "Symbol", "Span"):
        from .cpg import LiteCPG, Node, Edge, Symbol, Span
        return locals()[name]

    # Builder and parsing
    if name in ("LiteCPGBuilder", "ParsedFile"):
        from .builder import LiteCPGBuilder, ParsedFile
        return locals()[name]

    # Utilities
    if name in ("flatten_ts", "span_for"):
        from .ast_utils import flatten_ts, span_for
        return locals()[name]

    # Graph construction
    if name == "build_cfg":
        from .cfg import build_cfg
        return build_cfg
    if name == "extract_calls":
        from .calls import extract_calls
        return extract_calls

    # Analysis
    if name in ("build_def_use", "propagate_taint"):
        from .dataflow import build_def_use, propagate_taint
        return locals()[name]

    # Languages
    if name in ("create_parser", "normalize_lang"):
        from .languages import create_parser, normalize_lang
        return locals()[name]

    # Symbol indexing
    if name in ("SymbolIndex", "collect_symbols"):
        from .symbol_index import SymbolIndex, collect_symbols
        return locals()[name]

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = [
    "LiteCPG",
    "Node",
    "Edge",
    "Symbol",
    "Span",
    "LiteCPGBuilder",
    "ParsedFile",
    "flatten_ts",
    "span_for",
    "build_cfg",
    "extract_calls",
    "build_def_use",
    "propagate_taint",
    "create_parser",
    "normalize_lang",
    "SymbolIndex",
    "collect_symbols",
]
