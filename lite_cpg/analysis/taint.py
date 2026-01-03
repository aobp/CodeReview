"""Store-backed taint propagation for Lite-CPG (SQLite).

This is best-effort on top of persisted DDG + interprocedural call edges.
It treats certain call-sites as sources/sinks based on configured names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .source_sink import SourceSinkConfig, DEFAULT_SOURCE_SINK_CONFIG
from ..store.backends.sqlite import LiteCPGStore


@dataclass(frozen=True)
class TaintOptions:
    edge_kinds: Sequence[str] = ("DDG", "CFG_IP_CALL", "CALL")
    max_steps: int = 80
    max_paths: int = 50
    per_node_limit: int = 200


def forward_taint_paths_store(
    store: LiteCPGStore,
    *,
    lang: str,
    config: SourceSinkConfig = DEFAULT_SOURCE_SINK_CONFIG,
    options: TaintOptions = TaintOptions(),
) -> List[List[str]]:
    sources = store.call_sites_by_names(sorted(config.sources.get(lang, set())), lang=lang)
    sinks = set(store.call_sites_by_names(sorted(config.sinks.get(lang, set())), lang=lang))
    sanitizers = set(store.call_sites_by_names(sorted(config.sanitizers.get(lang, set())), lang=lang))
    return _paths(store, sources=sources, sinks=sinks, sanitizers=sanitizers, options=options, direction="out")


def backward_taint_paths_store(
    store: LiteCPGStore,
    *,
    lang: str,
    config: SourceSinkConfig = DEFAULT_SOURCE_SINK_CONFIG,
    options: TaintOptions = TaintOptions(),
) -> List[List[str]]:
    sinks = store.call_sites_by_names(sorted(config.sinks.get(lang, set())), lang=lang)
    sources = set(store.call_sites_by_names(sorted(config.sources.get(lang, set())), lang=lang))
    sanitizers = set(store.call_sites_by_names(sorted(config.sanitizers.get(lang, set())), lang=lang))
    return _paths(store, sources=sinks, sinks=sources, sanitizers=sanitizers, options=options, direction="in")


def _paths(
    store: LiteCPGStore,
    *,
    sources: Sequence[str],
    sinks: Set[str],
    sanitizers: Set[str],
    options: TaintOptions,
    direction: str,
) -> List[List[str]]:
    found: List[List[str]] = []
    for src in sources:
        if len(found) >= options.max_paths:
            break
        stack: List[Tuple[str, List[str]]] = [(src, [src])]
        visited: Set[str] = {src}
        while stack and len(found) < options.max_paths:
            node, path = stack.pop()
            if node in sinks:
                found.append(path)
                continue
            if len(path) >= options.max_steps:
                continue
            if node in sanitizers:
                continue
            neigh = store.neighbors_multi(
                node, kinds=list(options.edge_kinds), direction=direction, limit=options.per_node_limit
            )
            for nxt in neigh:
                if nxt in visited:
                    continue
                visited.add(nxt)
                stack.append((nxt, path + [nxt]))
    return found

