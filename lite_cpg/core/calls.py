"""Call graph extraction using tree-sitter syntax shapes."""

from __future__ import annotations

from typing import Dict, List, Tuple

from tree_sitter import Node as TSNode  # type: ignore

from .cpg import Edge
from .cfg import block_id


CALL_NODE_TYPES = {
    "call_expression",
    "function_call",
    "method_invocation",
    "constructor_invocation",
    # Ruby
    "call",
}

DECL_NODE_TYPES = {
    "function_declaration",
    "method_declaration",
    "function_definition",
    "function_item",  # rust/go like naming in some grammars
    "method_definition",
    # JS/TS: const foo = () => {}
    "variable_declarator",
    # Ruby
    "method",
}


def extract_calls(id_prefix: str, root: TSNode) -> Tuple[List[Edge], Dict[str, Tuple[str, TSNode]]]:
    """Return call edges (caller->callee) and symbol declarations with nodes."""
    symbols: Dict[str, Tuple[str, TSNode]] = {}
    call_edges: List[Edge] = []

    stack = [root]
    while stack:
        n = stack.pop()
        if n.type in DECL_NODE_TYPES:
            decl_id = block_id(id_prefix, n)
            name = identifier_text(n)
            if name:
                symbols[decl_id] = (name, n)
        if n.type in CALL_NODE_TYPES:
            call_id = block_id(id_prefix, n)
            callee = identifier_text(n)
            if callee:
                call_edges.append(Edge(src=call_id, dst=callee, kind="CALL", attrs={"unresolved": "true"}))
        stack.extend(reversed(n.children))
    return call_edges, symbols


def identifier_text(node: TSNode) -> str:
    # heuristic: prefer member/attribute/selector expressions as a whole
    for child in node.children:
        if child.type in {
            "attribute",  # Python
            "member_expression",  # JS/TS
            "field_expression",  # Rust/Go-like
            "selector_expression",  # Go
            "scoped_identifier",
        }:
            return child.text.decode("utf-8", errors="ignore")

    # otherwise find first identifier-like child
    for child in node.children:
        if "identifier" in child.type or child.type in {
            "property_identifier",
            "method_identifier",
            "type_identifier",
            "field_identifier",
        }:
            return child.text.decode("utf-8", errors="ignore")
    return ""
