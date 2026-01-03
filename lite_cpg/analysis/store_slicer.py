"""Store-backed slicing for Lite-CPG (SQLite).

Runs forward/backward slice directly against SQLite edges table to support large repos.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Set

from ..store.backends.sqlite import LiteCPGStore


DEFAULT_EDGE_POLICY = ("DDG", "CFG", "CFG_BRANCH", "CFG_IP_CALL", "CFG_IP_RET", "CALL")


@dataclass(frozen=True)
class SliceOptions:
    edge_kinds: Sequence[str] = DEFAULT_EDGE_POLICY
    max_nodes: int = 500
    per_node_limit: int = 200


def forward_slice_store(store: LiteCPGStore, criteria: Iterable[str], options: SliceOptions = SliceOptions()) -> List[str]:
    return _slice(store, criteria, direction="out", options=options)


def backward_slice_store(store: LiteCPGStore, criteria: Iterable[str], options: SliceOptions = SliceOptions()) -> List[str]:
    return _slice(store, criteria, direction="in", options=options)


def _slice(store: LiteCPGStore, criteria: Iterable[str], *, direction: str, options: SliceOptions) -> List[str]:
    q = deque()
    seen: Set[str] = set()
    out: List[str] = []

    for c in criteria:
        if c in seen:
            continue
        seen.add(c)
        q.append(c)

    while q and len(out) < options.max_nodes:
        cur = q.popleft()
        out.append(cur)
        neigh = store.neighbors_multi(
            cur, kinds=list(options.edge_kinds), direction=direction, limit=options.per_node_limit
        )
        for nxt in neigh:
            if nxt in seen:
                continue
            seen.add(nxt)
            q.append(nxt)
    return out

