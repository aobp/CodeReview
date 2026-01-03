"""Language loader and capability matrix for tree-sitter with local grammars."""

from __future__ import annotations

import ctypes
import functools
from pathlib import Path
from typing import Dict

try:
    # Optional prebuilt parsers
    from tree_sitter_languages import get_parser  # type: ignore
except Exception:
    get_parser = None  # type: ignore

try:
    from tree_sitter import Language, Parser  # type: ignore
except Exception:
    Language = None  # type: ignore
    Parser = None  # type: ignore


SUPPORTED_LANGUAGES = {
    "typescript": "typescript",
    "python": "python",
    "go": "go",
    "java": "java",
    "ruby": "ruby",
}

# Local grammar shared objects.
# NOTE: In this CodeReview integration we intentionally reuse the existing
# `codereview/code/lib/*.so` binaries (we do not copy binaries into CodeReview/).
#
# Path layout:
#   <repo_root>/CodeReview/lite_cpg/core/languages.py
#   <repo_root>/code/lib/*.so
#
# Allow override via env for portability.
import os

# Path calculation: from CodeReview/lite_cpg/core/languages.py to codereview/code/lib
# parents[0] = core/
# parents[1] = lite_cpg/
# parents[2] = CodeReview/
# parents[3] = codereview/  <- this is the repo root
_DEFAULT_LIB_DIR = Path(__file__).resolve().parents[3] / "code" / "lib"
_LIB_DIR = Path(os.environ.get("LITE_CPG_LIB_DIR", str(_DEFAULT_LIB_DIR))).resolve()

# Validate that lib directory exists at runtime (helpful error if path is wrong)
if not _LIB_DIR.exists():
    import warnings
    warnings.warn(
        f"Lite-CPG lib directory not found: {_LIB_DIR}\n"
        f"  Expected location: <repo_root>/code/lib/\n"
        f"  You can override with: export LITE_CPG_LIB_DIR=/path/to/code/lib",
        UserWarning
    )
LOCAL_SO = {
    "java": _LIB_DIR / "tree-sitter-java.so",
    "go": _LIB_DIR / "tree-sitter-go.so",
    "python": _LIB_DIR / "tree-sitter-python.so",
    # Use javascript grammar as a coarse fallback for typescript.
    "typescript": _LIB_DIR / "tree-sitter-javascript.so",
    # Optional ruby grammar if provided (may be absent; then provider/get_parser may still work).
    "ruby": _LIB_DIR / "tree-sitter-ruby.so",
}

LANGUAGE_FUNC = {
    "java": "tree_sitter_java",
    "go": "tree_sitter_go",
    "python": "tree_sitter_python",
    "typescript": "tree_sitter_javascript",
    "ruby": "tree_sitter_ruby",
}

LANGUAGE_PROVIDER_MODULE = {
    "python": "tree_sitter_python",
    "go": "tree_sitter_go",
    "java": "tree_sitter_java",
    "ruby": "tree_sitter_ruby",
    "typescript": "tree_sitter_javascript",  # best-effort
}


@functools.lru_cache(maxsize=None)
def create_parser(lang: str):
    """Create a parser for the given language.

    Resolution order:
    1) tree_sitter_<lang> provider module (recommended for tree_sitter>=0.22)
    2) local .so via ctypes + tree_sitter.Language + Parser
    3) tree_sitter_languages.get_parser (if installed and compatible)
    4) raise RuntimeError
    """
    if Parser is None or Language is None:  # pragma: no cover
        raise RuntimeError("tree_sitter is not installed")

    errors = []

    # 1) provider modules (tree_sitter_python/tree_sitter_go/...)
    provider_mod = LANGUAGE_PROVIDER_MODULE.get(lang)
    if provider_mod:
        try:
            mod = __import__(provider_mod)
            if hasattr(mod, "language"):
                cap = mod.language()
                language = Language(cap)
                parser = Parser()
                if hasattr(parser, "set_language"):
                    parser.set_language(language)
                else:
                    parser.language = language
                return parser
        except Exception as e:
            errors.append(f"provider_module({provider_mod}) failed: {e!r}")

    # 2) local .so using tree_sitter Language/Parser
    so_path = LOCAL_SO.get(lang)
    if so_path and so_path.exists():
        try:
            language = _load_language_from_so(lang, so_path)
            parser = Parser()
            if hasattr(parser, "set_language"):
                parser.set_language(language)  # tree_sitter<=0.20
            elif hasattr(parser, "language"):
                parser.language = language  # tree_sitter>=0.22
            else:  # pragma: no cover
                raise RuntimeError("Unsupported tree_sitter Parser API")
            return parser
        except Exception as e:
            errors.append(f"local_so({so_path}) failed: {e!r}")

    # 3) prebuilt parser from tree_sitter_languages (often incompatible with newer tree_sitter)
    if get_parser:
        try:
            return get_parser(lang)
        except Exception as e:
            errors.append(f"tree_sitter_languages.get_parser({lang}) failed: {e!r}")

    detail = "; ".join(errors) if errors else "no detailed error captured"
    raise RuntimeError(f"No parser available for language: {lang}. Details: {detail}")


def _load_language_from_so(lang: str, so_path: Path):
    """Load a tree-sitter Language from a grammar .so.

    Supports both old API (Language(path, name)) and new API (Language(ptr)).
    """
    if Language is None:  # pragma: no cover
        raise RuntimeError("tree_sitter is not installed")

    # Newer tree_sitter API expects a pointer to TSLanguage.
    func_name = LANGUAGE_FUNC.get(lang)
    if func_name:
        lib = ctypes.CDLL(str(so_path))
        if not hasattr(lib, func_name):
            raise RuntimeError(f"Grammar library missing symbol: {func_name}")
        func = getattr(lib, func_name)
        func.restype = ctypes.c_void_p
        ptr = func()
        if not ptr:
            raise RuntimeError(f"Failed to obtain TSLanguage* from {func_name}")
        try:
            return Language(ptr)
        except Exception:
            pass

    # Older API
    language_name = "javascript" if lang == "typescript" else lang
    return Language(str(so_path), language_name)


def capability_matrix() -> Dict[str, Dict[str, bool]]:
    """Return a coarse capability matrix for quick inspection."""
    return {
        "typescript": {"typed": False, "cfg": True, "calls": True},
        "python": {"typed": False, "cfg": True, "calls": True},
        "go": {"typed": False, "cfg": True, "calls": True},
        "java": {"typed": False, "cfg": True, "calls": True},
        "ruby": {"typed": False, "cfg": True, "calls": True},
    }


def normalize_lang(value: str) -> str:
    key = value.lower()
    if key not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {value}")
    return key
