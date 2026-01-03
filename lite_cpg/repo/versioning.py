"""Versioning helpers for Lite-CPG builds."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable


def repo_fingerprint(files: Iterable[Path]) -> str:
    h = hashlib.sha256()
    for path in sorted(files, key=lambda p: str(p)):
        h.update(str(path).encode())
        try:
            h.update(path.read_bytes())
        except Exception:
            continue
    return h.hexdigest()


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
