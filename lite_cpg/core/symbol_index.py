"""Symbol indexing and cross-file resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tree_sitter import Node as TSNode  # type: ignore

from .ast_utils import span_for
from .cpg import Symbol


DECL_KINDS = {
    "function_declaration",
    "function_definition",
    "method_declaration",
    "method_definition",
    "function_item",
    "class_declaration",
    "class_definition",
    "type_declaration",
    # Go
    "type_spec",
    "type_identifier",
    "type_declaration",
    "function_declaration",
    # Ruby
    "method",
    "class",
    "def",
}


@dataclass
class SymbolIndex:
    symbols: Dict[str, Symbol] = field(default_factory=dict)  # id -> symbol
    by_name: Dict[str, List[str]] = field(default_factory=dict)  # name -> [id]

    def add(self, sym: Symbol) -> None:
        self.symbols[sym.id] = sym
        self.by_name.setdefault(sym.name, []).append(sym.id)

    def resolve_name(self, name: str, lang: Optional[str] = None) -> List[str]:
        ids = self.by_name.get(name, [])
        if lang is None:
            return ids
        return [sid for sid in ids if self.symbols[sid].lang == lang]


def collect_symbols(path: Path, lang: str, root: TSNode, *, id_prefix: str) -> List[Symbol]:
    """Collect declarative symbols in a file."""
    symbols: List[Symbol] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in DECL_KINDS:
            name = _identifier_text(node)
            if name:
                symbols.append(
                    Symbol(
                        id=f"{id_prefix}:{node.start_byte}-{node.end_byte}",
                        name=name,
                        kind="function" if "function" in node.type or "method" in node.type else "type",
                        span=span_for(str(path), node),
                        lang=lang,
                        file=str(path),
                    )
                )
        elif lang == "typescript" and node.type == "variable_declarator":
            # TS/TSX frequently declares functions/components as:
            #   const Foo = () => { ... }
            #   const foo = function() { ... }
            name = _identifier_text(node)
            if name and _has_function_initializer(node):
                symbols.append(
                    Symbol(
                        id=f"{id_prefix}:{node.start_byte}-{node.end_byte}",
                        name=name,
                        kind="function",
                        span=span_for(str(path), node),
                        lang=lang,
                        file=str(path),
                    )
                )
        stack.extend(reversed(node.children))
    return symbols


def _identifier_text(node: TSNode) -> str:
    for child in node.children:
        if "identifier" in child.type or child.type in {
            "property_identifier",
            "method_identifier",
            "type_identifier",
            "field_identifier",
            # Ruby class/module names
            "constant",
        }:
            return child.text.decode("utf-8", errors="ignore")
    return ""


def _has_function_initializer(node: TSNode) -> bool:
    # Best-effort across JS/TS grammars
    for child in node.children:
        if child.type in {"arrow_function", "function", "function_expression"}:
            return True
    return False
