"""Lightweight CFG builder on top of tree-sitter."""

from __future__ import annotations

from typing import Dict, List, Tuple

from tree_sitter import Node as TSNode  # type: ignore

from .cpg import Edge
from .ast_utils import span_for


CONTROL_KINDS = {
    "if_statement",
    "for_statement",
    "while_statement",
    "do_statement",
    "switch_statement",
    "case_statement",
    "else_clause",
    "try_statement",
    "except_clause",
    "catch_clause",
    "finally_clause",
}


def build_cfg(path: str, lang: str, root: TSNode, *, id_prefix: str) -> List[Edge]:
    """Very lightweight CFG: connect sequential statements and branch targets."""
    basic_blocks: List[TSNode] = []
    collect_basic_blocks(root, basic_blocks)

    edges: List[Edge] = []
    for idx, block in enumerate(basic_blocks):
        current_id = block_id(id_prefix, block)
        # Sequential edge
        if idx + 1 < len(basic_blocks):
            edges.append(Edge(src=current_id, dst=block_id(id_prefix, basic_blocks[idx + 1]), kind="CFG"))

        # Branch edges (best effort, language-agnostic)
        if block.type in CONTROL_KINDS:
            for child in block.children:
                if is_branch_target(child):
                    edges.append(Edge(src=current_id, dst=block_id(id_prefix, child), kind="CFG_BRANCH"))
    return edges


def collect_basic_blocks(node: TSNode, out: List[TSNode]) -> None:
    """Collect nodes that serve as basic block representatives."""
    if is_statement(node):
        out.append(node)
    for child in node.children:
        collect_basic_blocks(child, out)


def is_statement(node: TSNode) -> bool:
    return (
        node.type.endswith("_statement")
        or node.type in {"expression_statement", "return_statement", "break_statement", "continue_statement"}
    )


def is_branch_target(node: TSNode) -> bool:
    return is_statement(node) or node.type.endswith("_clause")


def block_id(id_prefix: str, node: TSNode) -> str:
    return f"{id_prefix}:{node.start_byte}-{node.end_byte}"
