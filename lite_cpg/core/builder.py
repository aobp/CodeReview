"""Lite-CPG builder orchestrating tree-sitter parsing and graph assembly."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List

from .ast_utils import flatten_ts, span_for
from .calls import extract_calls
from .cfg import build_cfg
from .cpg import LiteCPG, Symbol
from .languages import create_parser, normalize_lang
from ..analysis.source_sink import SourceSinkConfig, DEFAULT_SOURCE_SINK_CONFIG
from .symbol_index import SymbolIndex, collect_symbols
from ..repo.scan import RepoScanConfig, scan_repo
from ..repo.versioning import content_hash


@dataclass
class ParsedFile:
    path: Path
    lang: str
    source: bytes
    blob_hash: str


class LiteCPGBuilder:
    def __init__(
        self,
        source_sink: SourceSinkConfig = DEFAULT_SOURCE_SINK_CONFIG,
    ) -> None:
        self.source_sink = source_sink

    def parse_files(self, files: Iterable[Path], lang: str) -> List[ParsedFile]:
        """Parse files and attach tree-sitter root for reuse."""
        lang = normalize_lang(lang)
        parser = create_parser(lang)
        parsed: List[ParsedFile] = []
        for path in files:
            src = path.read_bytes()
            tree = parser.parse(src)
            root = tree.root_node
            pf = ParsedFile(path=path, lang=lang, source=src, blob_hash=content_hash(src))
            pf.root = root  # type: ignore[attr-defined]
            parsed.append(pf)
        return parsed

    def parse_repo(self, repo_root: Path, config: RepoScanConfig = RepoScanConfig()) -> List[ParsedFile]:
        """Scan and parse an entire repository."""
        files_by_lang = scan_repo(repo_root, config=config)
        parsed: List[ParsedFile] = []
        for lang, files in files_by_lang.items():
            parsed.extend(self.parse_files(files, lang=lang))
        return parsed

    def build_repo(self, repo_root: Path, config: RepoScanConfig = RepoScanConfig()) -> LiteCPG:
        """Scan, parse and build a repository-level Lite-CPG."""
        return self.build(self.parse_repo(repo_root, config=config), interprocedural=True)

    def build(self, parsed_files: Iterable[ParsedFile], interprocedural: bool = False) -> LiteCPG:
        """Build Lite-CPG (AST+CFG+call graph+symbol table+source/sink tags)."""
        cpg = LiteCPG()
        sym_index = SymbolIndex()

        # First pass: collect symbols to enable cross-file resolution
        for pf in parsed_files:
            root = getattr(pf, "root")
            for sym in collect_symbols(pf.path, pf.lang, root, id_prefix=pf.blob_hash):
                cpg.add_symbol(sym)
                sym_index.add(sym)

        # Second pass: build graphs and resolve calls
        parsed_files = list(parsed_files)
        for pf in parsed_files:
            root = getattr(pf, "root")
            nodes, ast_edges = flatten_ts(str(pf.path), pf.lang, root, pf.source, id_prefix=pf.blob_hash)
            for n in nodes:
                cpg.add_node(n)
            for src, dst, kind in ast_edges:
                cpg.add_edge(src, dst, kind)

            cfg_edges = build_cfg(str(pf.path), pf.lang, root, id_prefix=pf.blob_hash)
            cpg.edges.extend(cfg_edges)

            call_edges, decls = extract_calls(pf.blob_hash, root)
            for decl_id, (name, node) in decls.items():
                # if already collected, enrich with better span if needed
                if decl_id not in cpg.symbols:
                    symbol = Symbol(
                        id=decl_id,
                        name=name,
                        kind="function",
                        span=span_for(str(pf.path), node),
                        lang=pf.lang,
                        file=str(pf.path),
                    )
                    cpg.add_symbol(symbol)
                    sym_index.add(symbol)

            # resolve calls to known symbols (cross-file)
            for edge in call_edges:
                candidates = sym_index.resolve_name(edge.dst, pf.lang)
                if candidates:
                    edge.attrs.pop("unresolved", None)
                    edge.dst = candidates[0]
                cpg.call_graph.append(edge)
                if interprocedural and not edge.attrs.get("unresolved"):
                    cpg.add_edge(edge.src, edge.dst, "CFG_IP_CALL")
                    cpg.add_edge(edge.dst, edge.src, "CFG_IP_RET")

            self._tag_sources_sinks(cpg, pf.lang)
        return cpg

    def _tag_sources_sinks(self, cpg: LiteCPG, lang: str) -> None:
        for sym in cpg.symbols.values():
            if sym.lang != lang:
                continue
            if self.source_sink.is_source(lang, sym.name):
                sym.kind = "source"
            if self.source_sink.is_sink(lang, sym.name):
                sym.kind = "sink"
