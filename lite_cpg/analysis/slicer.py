"""Backward/forward slicing utilities on Lite-CPG."""

from __future__ import annotations

from collections import deque
from typing import Iterable, List, Set

from ..core.cpg import LiteCPG


def backward_slice(cpg: LiteCPG, criteria: Iterable[str], max_nodes: int = 200) -> List[str]:
    graph = _make_reverse_graph(cpg)
    return _bfs(graph, criteria, max_nodes)


def forward_slice(cpg: LiteCPG, criteria: Iterable[str], max_nodes: int = 200) -> List[str]:
    graph = _make_forward_graph(cpg)
    return _bfs(graph, criteria, max_nodes)


def _make_forward_graph(cpg: LiteCPG):
    g = {}
    for e in cpg.edges + cpg.call_graph:
        g.setdefault(e.src, []).append(e.dst)
    return g


def _make_reverse_graph(cpg: LiteCPG):
    g = {}
    for e in cpg.edges + cpg.call_graph:
        g.setdefault(e.dst, []).append(e.src)
    return g


def _bfs(graph, starts: Iterable[str], limit: int) -> List[str]:
    out: List[str] = []
    q = deque()
    seen: Set[str] = set()
    for s in starts:
        q.append(s)
        seen.add(s)
    while q and len(out) < limit:
        cur = q.popleft()
        out.append(cur)
        for nxt in graph.get(cur, []):
            if nxt in seen:
                continue
            seen.add(nxt)
            q.append(nxt)
    return out
