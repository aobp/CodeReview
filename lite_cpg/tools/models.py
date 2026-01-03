"""Tool I/O models for repo-scale code intelligence.

These models are designed to be:
- Stable for LLM tool-calling (predictable keys, minimal nesting surprises)
- Location-first (file + start/end line/col always available where possible)
- Serializable (pure dict/list/str/int/bool/float)
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class Location:
    file_path: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int


@dataclass(frozen=True)
class ToolError:
    message: str
    details: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class SymbolHit:
    symbol_id: str
    name: str
    kind: str
    lang: str
    location: Location
    attrs: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class NodeHit:
    node_id: str
    kind: str
    location: Location
    attrs: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class CallHit:
    src_node_id: str
    dst_name: str
    dst_symbol_id: Optional[str]
    resolved: bool
    location: Location
    attrs: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class ImportHit:
    file_path: str
    lang: str
    import_text: str
    location: Location
    resolved_path: Optional[str] = None
    resolved_symbol_id: Optional[str] = None


@dataclass(frozen=True)
class PathResult:
    """A graph path with node ids and best-effort locations for each node."""

    node_ids: List[str]
    edge_kinds: Optional[List[str]] = None
    locations: Optional[List[Location]] = None


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: Any = None
    error: Optional[ToolError] = None
    meta: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Keep payload minimal and predictable
        if d.get("error") is None:
            d.pop("error", None)
        if d.get("meta") is None:
            d.pop("meta", None)
        return d


def ok(data: Any = None, *, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return ToolResult(ok=True, data=data, meta=meta).to_dict()


def fail(message: str, *, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return ToolResult(ok=False, error=ToolError(message=message, details=details)).to_dict()


