"""AST helpers to turn tree-sitter nodes into Lite-CPG nodes."""

from __future__ import annotations

from typing import List, Optional, Tuple

from tree_sitter import Node as TSNode  # type: ignore

from .cpg import Node, Span


def span_for(path: str, node: TSNode) -> Span:
    sl, sc = node.start_point
    el, ec = node.end_point
    return (path, sl + 1, sc + 1, el + 1, ec + 1)


def flatten_ts(
    path: str,
    lang: str,
    node: TSNode,
    source: bytes,
    *,
    id_prefix: Optional[str] = None,
    parent_id: Optional[str] = None,
    nodes: Optional[List[Node]] = None,
    edges: Optional[List[Tuple[str, str, str]]] = None,
) -> Tuple[List[Node], List[Tuple[str, str, str]]]:
    """Preorder traversal to collect Node + AST edges."""
    if nodes is None:
        nodes = []
    if edges is None:
        edges = []

    prefix = id_prefix or path
    node_id = f"{prefix}:{node.start_byte}-{node.end_byte}"
    text = source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
    attrs = {
        "path": path,
        "start_byte": str(node.start_byte),
        "end_byte": str(node.end_byte),
    }
    nodes.append(
        Node(
            id=node_id,
            kind=node.type,
            span=span_for(path, node),
            text=text,
            lang=lang,
            attrs=attrs,
        )
    )
    if parent_id:
        edges.append((parent_id, node_id, "AST"))

    for child in node.children:
        flatten_ts(
            path,
            lang,
            child,
            source,
            id_prefix=id_prefix,
            parent_id=node_id,
            nodes=nodes,
            edges=edges,
        )
    return nodes, edges
