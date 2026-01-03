"""Core Lite-CPG data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


Span = Tuple[str, int, int, int, int]  # (path, start_line, start_col, end_line, end_col)


@dataclass
class Node:
    id: str
    kind: str
    span: Span
    text: Optional[str] = None
    lang: Optional[str] = None
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass
class Edge:
    src: str
    dst: str
    kind: str
    attrs: Dict[str, str] = field(default_factory=dict)


@dataclass
class Symbol:
    id: str
    name: str
    kind: str
    span: Span
    lang: str
    file: str
    refs: List[str] = field(default_factory=list)
    calls: List[str] = field(default_factory=list)


@dataclass
class LiteCPG:
    """A minimal but reusable CPG representation."""

    nodes: Dict[str, Node] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)
    symbols: Dict[str, Symbol] = field(default_factory=dict)
    call_graph: List[Edge] = field(default_factory=list)

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node

    def add_edge(self, src: str, dst: str, kind: str) -> None:
        self.edges.append(Edge(src=src, dst=dst, kind=kind))

    def add_symbol(self, symbol: Symbol) -> None:
        self.symbols[symbol.id] = symbol

    def add_call(self, caller: str, callee: str) -> None:
        self.call_graph.append(Edge(src=caller, dst=callee, kind="CALL"))
