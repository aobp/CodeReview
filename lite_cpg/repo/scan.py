"""Repository scanning utilities for Lite-CPG."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set


EXT_TO_LANG = {
    ".py": "python",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".ts": "typescript",
    ".tsx": "typescript",
    # treat JS/JSX as typescript grammar fallback (we use JS grammar under the hood)
    ".js": "typescript",
    ".jsx": "typescript",
}


DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
    "dist",
    "build",
    "target",
    "vendor",
    ".venv",
    "venv",
}


@dataclass(frozen=True)
class RepoScanConfig:
    include_langs: Optional[Set[str]] = None
    exclude_dirs: Set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDE_DIRS))
    max_file_bytes: int = 2_000_000


def infer_language(path: Path) -> Optional[str]:
    return EXT_TO_LANG.get(path.suffix.lower())


def scan_repo(root: Path, config: RepoScanConfig = RepoScanConfig()) -> Dict[str, List[Path]]:
    """Scan a repo and return files grouped by language."""
    root = root.resolve()
    results: Dict[str, List[Path]] = {}
    for path in root.rglob("*"):
        if path.is_dir():
            # prune common large dirs
            if path.name in config.exclude_dirs:
                # rglob doesn't support pruning directly; skip by continuing and letting is_file filter
                continue
            continue
        if not path.is_file():
            continue
        # exclude by parent directory name
        if any(part in config.exclude_dirs for part in path.parts):
            continue
        try:
            if path.stat().st_size > config.max_file_bytes:
                continue
        except OSError:
            continue

        lang = infer_language(path)
        if not lang:
            continue
        if config.include_langs and lang not in config.include_langs:
            continue
        results.setdefault(lang, []).append(path)
    # stable ordering
    for lang in results:
        results[lang] = sorted(results[lang], key=lambda p: str(p))
    return results
