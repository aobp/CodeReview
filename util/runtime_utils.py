"""Runtime timing helpers for console logs."""

from __future__ import annotations

import time
from typing import Any, Dict, Mapping


def ensure_run_started(metadata: Dict[str, Any]) -> None:
    if "run_started_at" not in metadata:
        metadata["run_started_at"] = time.monotonic()


def elapsed_seconds(metadata: Mapping[str, Any]) -> float:
    started = metadata.get("run_started_at")
    try:
        if started is None:
            return 0.0
        return max(0.0, float(time.monotonic() - float(started)))
    except Exception:
        return 0.0


def format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    m, s = divmod(seconds, 60.0)
    h, m = divmod(m, 60.0)
    if h >= 1:
        return f"{int(h)}h{int(m):02d}m{s:05.2f}s"
    if m >= 1:
        return f"{int(m)}m{s:05.2f}s"
    return f"{s:.2f}s"


def elapsed_tag(metadata: Mapping[str, Any]) -> str:
    return f"t+{format_duration(elapsed_seconds(metadata))}"

