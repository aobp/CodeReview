"""Best-effort def-use and taint propagation on Lite-CPG."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set

from tree_sitter import Node as TSNode  # type: ignore

from .cpg import Edge, LiteCPG
from .cfg import block_id


ASSIGN_NODE_TYPES = {
    "assignment_expression",
    "variable_declarator",
    "augmented_assignment_expression",
    "assignment",  # python
}

IDENT_TYPES = {"identifier", "property_identifier", "field_identifier"}
CALL_TYPES = {"call_expression", "function_call", "method_invocation", "constructor_invocation", "call"}


@dataclass
class DefUseResult:
    ddg_edges: List[Edge]


def build_def_use(cpg: LiteCPG, root: TSNode, *, id_prefix: str) -> DefUseResult:
    """Build simple def-use edges within a file (not SSA, but helpful for slicing/taint)."""
    last_def: Dict[str, str] = {}  # var name -> node id
    ddg: List[Edge] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if _is_assign(node):
            target = _first_ident_desc(node)
            if target:
                def_id = block_id(id_prefix, node)
                last_def[target] = def_id
                # Connect RHS call to the definition node if present (x = source()).
                rhs_call = _first_call_desc(node)
                if rhs_call is not None:
                    call_id = block_id(id_prefix, rhs_call)
                    ddg.append(Edge(src=call_id, dst=def_id, kind="DDG", attrs={"var": target, "via": "rhs_call"}))
        elif node.type in IDENT_TYPES:
            name = node.text.decode("utf-8", errors="ignore")
            if name in last_def:
                use_id = block_id(id_prefix, node)
                ddg.append(Edge(src=last_def[name], dst=use_id, kind="DDG", attrs={"var": name}))
        elif node.type in CALL_TYPES:
            call_id = block_id(id_prefix, node)
            # Connect arg identifier uses to the call node (sink reachability).
            for ident in _all_idents_desc(node):
                name = ident.text.decode("utf-8", errors="ignore")
                if name in last_def:
                    ddg.append(
                        Edge(
                            src=last_def[name],
                            dst=call_id,
                            kind="DDG",
                            attrs={"var": name, "via": "arg"},
                        )
                    )
        stack.extend(reversed(node.children))
    cpg.edges.extend(ddg)
    return DefUseResult(ddg_edges=ddg)


def propagate_taint(
    cpg: LiteCPG,
    source_ids: Set[str],
    sink_predicate,
    max_steps: int = 64,
) -> List[List[str]]:
    """Propagate taint along DDG and CALL edges; return paths reaching sinks."""
    graph: Dict[str, List[str]] = {}
    for e in cpg.edges:
        if e.kind == "DDG":
            graph.setdefault(e.src, []).append(e.dst)
    for e in cpg.call_graph:
        graph.setdefault(e.src, []).append(e.dst)

    paths: List[List[str]] = []
    for src in source_ids:
        stack = [(src, [src])]
        visited = {src}
        while stack and len(paths) < 1000:
            node, path = stack.pop()
            if sink_predicate(node):
                paths.append(path)
                continue
            if len(path) > max_steps:
                continue
            for nxt in graph.get(node, []):
                if nxt in visited:
                    continue
                visited.add(nxt)
                stack.append((nxt, path + [nxt]))
    return paths


def _is_assign(node: TSNode) -> bool:
    return node.type in ASSIGN_NODE_TYPES or "assignment" in node.type


def _first_ident_desc(node: TSNode):
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in IDENT_TYPES:
            return n.text.decode("utf-8", errors="ignore")
        stack.extend(reversed(n.children))
    return ""


def _first_call_desc(node: TSNode):
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in CALL_TYPES:
            return n
        stack.extend(reversed(n.children))
    return None


def _all_idents_desc(node: TSNode):
    out = []
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in IDENT_TYPES:
            out.append(n)
        stack.extend(reversed(n.children))
    return out
