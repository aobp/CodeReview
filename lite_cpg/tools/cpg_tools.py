"""Repo-scale tool functions (pure Python) for LLM usage.

All functions are read-only and designed to be called after indexing:
1) Run index_repository(repo_root=..., store=LiteCPGStore(...), rev=..., store_blobs=True recommended)
2) Call tools with (db_path, rev, ...) to query that specific revision.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..core.languages import create_parser
from .models import CallHit, ImportHit, Location, NodeHit, PathResult, SymbolHit, fail, ok
from .store_helpers import (
    blob_content,
    file_version_blob,
    file_exists_at_rev,
    find_files_endingwith,
    iter_edges_for_rev,
    node_location,
    node_locations,
    open_store,
    require_rev,
    symbol_row_at_rev,
)


# ----------------------------
# Symbol search
# ----------------------------


def symbol_search(
    *,
    db_path: str,
    query: str,
    rev: Optional[str] = None,
    lang: Optional[str] = None,
    file_path: Optional[str] = None,
    limit: int = 50,
    include_callsites: bool = True,
    exact_name: bool = True,
) -> Dict[str, Any]:
    """Find symbol definitions (and optionally call sites) for a revision."""
    store = open_store(db_path)
    try:
        r = require_rev(store, rev)
        cur = store.conn.cursor()
        def _fetch_symbols(*, allow_like: bool) -> List[SymbolHit]:
            where_params: List[Any] = [r]
            where = ["fv.rev = ?"]
            if lang:
                where.append("f.lang = ?")
                where_params.append(lang)
            if file_path:
                where.append("f.path = ?")
                where_params.append(file_path)

            if allow_like:
                where.append("(s.name = ? OR s.name LIKE ?)")
                where_params.extend([query, f"%{query}%"])
                order_by = "ORDER BY (s.name = ?) DESC, s.start_line ASC, s.start_col ASC"
                order_params: List[Any] = [query]
            else:
                where.append("s.name = ?")
                where_params.append(query)
                order_by = "ORDER BY s.start_line ASC, s.start_col ASC"
                order_params = []

            cur.execute(
                f"""
                SELECT s.symbol_id, s.name, s.kind, s.lang,
                       f.path, s.start_line, s.start_col, s.end_line, s.end_col, s.attrs
                  FROM symbols s
                  JOIN files f ON f.file_id = s.file_id
                  JOIN file_versions fv ON fv.file_id = s.file_id AND fv.blob_hash = s.blob_hash
                 WHERE {' AND '.join(where)}
                 {order_by}
                 LIMIT ?;
                """,
                tuple(where_params + order_params + [int(limit)]),
            )
            hits: List[SymbolHit] = []
            for sid, name, kind, slang, path, sl, sc, el, ec, attrs in cur.fetchall():
                try:
                    attrs_dict = json.loads(attrs) if attrs else {}
                except Exception:
                    attrs_dict = {}
                hits.append(
                    SymbolHit(
                        symbol_id=str(sid),
                        name=str(name),
                        kind=str(kind),
                        lang=str(slang),
                        location=Location(
                            file_path=str(path),
                            start_line=int(sl),
                            start_col=int(sc),
                            end_line=int(el),
                            end_col=int(ec),
                        ),
                        attrs=attrs_dict or None,
                    )
                )
            return hits

        # Default: exact match only. If nothing matches exactly, fall back to LIKE.
        hits = _fetch_symbols(allow_like=not bool(exact_name))
        if exact_name and not hits:
            hits = _fetch_symbols(allow_like=True)

        callsites: List[NodeHit] = []
        if include_callsites and hits:
            # For exact_name mode, this usually collapses to [query], which keeps callsites small and focused.
            names = sorted({h.name for h in hits})
            placeholders = ",".join(["?"] * len(names))
            params2: List[Any] = [r]
            where2 = ["fv.rev = ?"]
            if lang:
                where2.append("f.lang = ?")
                params2.append(lang)
            if file_path:
                where2.append("f.path = ?")
                params2.append(file_path)
            params2.extend(names)
            params2.append(int(limit * 20))
            cur.execute(
                f"""
                SELECT DISTINCT c.src_node
                  FROM calls c
                  JOIN files f ON f.file_id = c.file_id
                  JOIN file_versions fv ON fv.file_id = c.file_id AND fv.blob_hash = c.blob_hash
                 WHERE {' AND '.join(where2)} AND c.dst_name IN ({placeholders})
                 LIMIT ?;
                """,
                tuple(params2),
            )
            for (node_id,) in cur.fetchall():
                loc = node_location(store, str(node_id))
                if not loc:
                    continue
                callsites.append(NodeHit(node_id=str(node_id), kind="callsite", location=loc))

        return ok(
            {
                "rev": r,
                "query": query,
                "symbols": [asdict(h) for h in hits],
                "callsites": [asdict(n) for n in callsites],
            }
        )
    except Exception as e:
        return fail("symbol_search failed", details={"error": str(e)})
    finally:
        store.close()


# ----------------------------
# AST index (defs/calls/imports)
# ----------------------------


def ast_index(
    *,
    db_path: str,
    rev: Optional[str] = None,
    file_paths: Optional[Sequence[str]] = None,
    lang: Optional[str] = None,
    include_defs: bool = True,
    include_calls: bool = True,
    include_imports: bool = True,
    limit_per_file: int = 500,
) -> Dict[str, Any]:
    """Return per-file defs/calls/imports for a revision (repo-scale, SQLite-first)."""
    store = open_store(db_path)
    try:
        r = require_rev(store, rev)
        cur = store.conn.cursor()

        file_filter_sql = ""
        params: List[Any] = [r]
        if file_paths:
            placeholders = ",".join(["?"] * len(file_paths))
            file_filter_sql += f" AND f.path IN ({placeholders})"
            params.extend(list(file_paths))
        if lang:
            file_filter_sql += " AND f.lang = ?"
            params.append(lang)

        cur.execute(
            f"""
            SELECT f.path, f.lang, fv.file_id, fv.blob_hash
              FROM file_versions fv
              JOIN files f ON f.file_id = fv.file_id
             WHERE fv.rev = ? {file_filter_sql}
             ORDER BY f.path ASC;
            """,
            tuple(params),
        )
        files = [(str(p), str(l), int(fid), str(bh)) for (p, l, fid, bh) in cur.fetchall()]
        out: Dict[str, Any] = {"rev": r, "files": []}

        for path, flang, file_id, blob_hash in files:
            file_entry: Dict[str, Any] = {"path": path, "lang": flang}

            if include_defs:
                cur.execute(
                    """
                    SELECT symbol_id, name, kind, lang, start_line, start_col, end_line, end_col, attrs
                      FROM symbols
                     WHERE file_id=? AND blob_hash=?
                     ORDER BY start_line ASC, start_col ASC
                     LIMIT ?;
                    """,
                    (file_id, blob_hash, int(limit_per_file)),
                )
                defs: List[Dict[str, Any]] = []
                for sid, name, kind, slang, sl, sc, el, ec, attrs in cur.fetchall():
                    try:
                        attrs_dict = json.loads(attrs) if attrs else {}
                    except Exception:
                        attrs_dict = {}
                    defs.append(
                        asdict(
                            SymbolHit(
                                symbol_id=str(sid),
                                name=str(name),
                                kind=str(kind),
                                lang=str(slang),
                                location=Location(path, int(sl), int(sc), int(el), int(ec)),
                                attrs=attrs_dict or None,
                            )
                        )
                    )
                file_entry["defs"] = defs

            if include_calls:
                cur.execute(
                    """
                    SELECT c.src_node, c.dst_name, c.dst_symbol, c.resolved, c.attrs
                      FROM calls c
                     WHERE c.file_id=? AND c.blob_hash=?
                     LIMIT ?;
                    """,
                    (file_id, blob_hash, int(limit_per_file)),
                )
                calls: List[Dict[str, Any]] = []
                for src_node, dst_name, dst_symbol, resolved, attrs in cur.fetchall():
                    loc = node_location(store, str(src_node))
                    if not loc:
                        continue
                    try:
                        attrs_dict = json.loads(attrs) if attrs else {}
                    except Exception:
                        attrs_dict = {}
                    calls.append(
                        asdict(
                            CallHit(
                                src_node_id=str(src_node),
                                dst_name=str(dst_name),
                                dst_symbol_id=str(dst_symbol) if dst_symbol else None,
                                resolved=bool(int(resolved)),
                                location=loc,
                                attrs=attrs_dict or None,
                            )
                        )
                    )
                file_entry["calls"] = calls

            if include_imports:
                # Deterministic extraction using tree-sitter on stored blob (requires store_blobs=True during indexing).
                src = blob_content(store, blob_hash)
                if src is None:
                    file_entry["imports_error"] = "blob content not available; index_repository(..., store_blobs=True) recommended"
                else:
                    imports = _extract_imports(path=path, lang=flang, source=src)
                    file_entry["imports"] = [asdict(i) for i in imports][: int(limit_per_file)]

            out["files"].append(file_entry)

        return ok(out)
    except Exception as e:
        return fail("ast_index failed", details={"error": str(e)})
    finally:
        store.close()


def ts_index(**kwargs) -> Dict[str, Any]:
    """Alias of ast_index (kept for tool.md naming)."""
    return ast_index(**kwargs)


def _extract_imports(*, path: str, lang: str, source: bytes) -> List[ImportHit]:
    try:
        parser = create_parser(lang)
    except Exception:
        # For ruby (and others), parser may be unavailable depending on environment.
        # We keep strict behavior for resolve_import, but for ast_index imports we can best-effort.
        if lang == "ruby":
            return _ruby_imports_fallback(path, source)
        return []
    tree = parser.parse(source)
    root = tree.root_node
    out: List[ImportHit] = []
    stack = [root]
    while stack:
        n = stack.pop()
        if lang == "python" and n.type in {"import_statement", "import_from_statement"}:
            out.append(_import_hit_from_node(path, lang, source, n))
        elif lang == "typescript" and n.type in {"import_statement"}:
            out.append(_import_hit_from_node(path, lang, source, n))
        elif lang == "go" and n.type in {"import_declaration", "import_spec"}:
            out.append(_import_hit_from_node(path, lang, source, n))
        elif lang == "java" and n.type in {"import_declaration"}:
            out.append(_import_hit_from_node(path, lang, source, n))
        elif lang == "ruby":
            # Ruby uses call nodes; capture require/require_relative best-effort
            if n.type in {"call", "method_call"}:
                txt = source[n.start_byte : n.end_byte].decode("utf-8", errors="ignore").strip()
                if txt.startswith("require ") or txt.startswith("require_relative "):
                    out.append(_import_hit_from_node(path, lang, source, n))
        stack.extend(reversed(n.children))
    return [x for x in out if x is not None]


def _import_hit_from_node(path: str, lang: str, source: bytes, node) -> ImportHit:
    sl, sc = node.start_point
    el, ec = node.end_point
    text = source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
    return ImportHit(
        file_path=path,
        lang=lang,
        import_text=text.strip(),
        location=Location(file_path=path, start_line=sl + 1, start_col=sc + 1, end_line=el + 1, end_col=ec + 1),
    )


def _ruby_imports_fallback(path: str, source: bytes) -> List[ImportHit]:
    """Fallback when ruby parser is unavailable: regex require/require_relative with line-level locations."""
    text = source.decode("utf-8", errors="ignore")
    out: List[ImportHit] = []
    for i, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if s.startswith("require ") or s.startswith("require_relative "):
            # best-effort columns
            start_col = line.find(s) + 1 if s in line else 1
            end_col = start_col + len(s)
            out.append(
                ImportHit(
                    file_path=path,
                    lang="ruby",
                    import_text=s,
                    location=Location(file_path=path, start_line=i, start_col=start_col, end_line=i, end_col=end_col),
                )
            )
    return out


# ----------------------------
# Signature + import resolution
# ----------------------------


def get_signature(
    *,
    db_path: str,
    qualified_name: str,
    rev: Optional[str] = None,
    lang: Optional[str] = None,
    limit: int = 5,
) -> Dict[str, Any]:
    """Resolve a function/class signature by name or symbol_id for a revision."""
    store = open_store(db_path)
    try:
        r = require_rev(store, rev)
        cur = store.conn.cursor()

        # If qualified_name looks like a symbol_id, prefer exact.
        if ":" in qualified_name and "-" in qualified_name:
            sym_row = symbol_row_at_rev(store, rev=r, symbol_id=qualified_name)
            if not sym_row:
                return fail("symbol not found at rev", details={"rev": r, "symbol_id": qualified_name})
            sig = _signature_for_symbol_row(store, sym_row)
            return ok({"rev": r, "symbol": sym_row["symbol_id"], "file_path": sym_row["file_path"], "location": asdict(sym_row["location"]), "signature": sig})

        # Otherwise resolve by name -> symbol_ids, scoped by lang if provided.
        symbol_ids = store.resolve_symbol_ids(qualified_name, lang=lang, limit=int(limit))
        if not symbol_ids:
            return fail("no symbols found for name", details={"rev": r, "name": qualified_name, "lang": lang})

        results = []
        for sid in symbol_ids:
            sym_row = symbol_row_at_rev(store, rev=r, symbol_id=sid)
            if not sym_row:
                continue
            sig = _signature_for_symbol_row(store, sym_row)
            results.append(
                {
                    "symbol_id": sym_row["symbol_id"],
                    "name": sym_row["name"],
                    "kind": sym_row["kind"],
                    "lang": sym_row["lang"],
                    "file_path": sym_row["file_path"],
                    "location": asdict(sym_row["location"]),
                    "signature": sig,
                }
            )
        return ok({"rev": r, "query": qualified_name, "results": results})
    except Exception as e:
        return fail("get_signature failed", details={"error": str(e)})
    finally:
        store.close()


def _signature_for_symbol_row(store, sym_row: Dict[str, Any]) -> str:
    # Prefer repomap_symbols.signature if present
    cur = store.conn.cursor()
    cur.execute("SELECT signature FROM repomap_symbols WHERE symbol_id=? LIMIT 1;", (sym_row["symbol_id"],))
    row = cur.fetchone()
    if row and row[0]:
        return str(row[0])

    src = blob_content(store, sym_row["blob_hash"])
    if src is None:
        return ""
    try:
        parser = create_parser(sym_row["lang"])
    except Exception:
        return ""
    tree = parser.parse(src)
    root = tree.root_node
    start_b = int(sym_row["start_byte"])
    end_b = int(sym_row["end_byte"])
    node = _find_node_by_byte_range(root, start_b, end_b)
    if node is None:
        return ""
    return _best_effort_signature_text(sym_row["lang"], src, node)


def _find_node_by_byte_range(root, start_b: int, end_b: int):
    stack = [root]
    while stack:
        n = stack.pop()
        if n.start_byte == start_b and n.end_byte == end_b:
            return n
        # Only descend if range overlaps
        if n.start_byte <= start_b and n.end_byte >= end_b:
            stack.extend(reversed(n.children))
    return None


def _best_effort_signature_text(lang: str, src: bytes, node) -> str:
    # For now, return a compact first-line signature snippet.
    text = src[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
    first = text.strip().splitlines()[0].strip()
    if lang == "python":
        return first  # "def foo(...):" or "class Bar:"
    if lang == "typescript":
        # likely "function foo(...)" / "const foo = (...)" / "class X"
        return first
    return first


def resolve_import(
    *,
    db_path: str,
    rev: Optional[str] = None,
    lang: str,
    from_module: str,
    name: str,
    repo_root_hint: Optional[str] = None,
    importer_file_path: Optional[str] = None,
    max_depth: int = 8,
) -> Dict[str, Any]:
    """Resolve an import with strict export-chain validation.

    Strict means: we only return success when we can *prove* the name is available
    from the module according to language semantics (including re-exports).
    If we cannot confirm, we fail (no guessing).
    """
    store = open_store(db_path)
    try:
        r = require_rev(store, rev)
        if lang not in {"python", "typescript", "go", "java", "ruby"}:
            return fail("unsupported lang for resolve_import", details={"lang": lang})

        if lang == "python":
            return _resolve_import_python(
                store=store,
                rev=r,
                from_module=from_module,
                name=name,
                repo_root_hint=repo_root_hint,
                importer_file_path=importer_file_path,
            )
        if lang == "typescript":
            return _resolve_import_ts(
                store=store,
                rev=r,
                from_module=from_module,
                name=name,
                repo_root_hint=repo_root_hint,
                importer_file_path=importer_file_path,
                max_depth=max_depth,
            )
        if lang == "go":
            return _resolve_import_go(
                store=store,
                rev=r,
                from_module=from_module,
                name=name,
                repo_root_hint=repo_root_hint,
            )
        if lang == "java":
            return _resolve_import_java(
                store=store,
                rev=r,
                from_module=from_module,
                name=name,
                repo_root_hint=repo_root_hint,
            )
        if lang == "ruby":
            return _resolve_import_ruby(
                store=store,
                rev=r,
                from_module=from_module,
                name=name,
                repo_root_hint=repo_root_hint,
                importer_file_path=importer_file_path,
            )

    except Exception as e:
        return fail("resolve_import failed", details={"error": str(e)})
    finally:
        store.close()


def _python_module_candidates_abs(module: str, *, repo_root: str, importer_file_path: Optional[str]) -> List[str]:
    # Support:
    # - absolute file path (module endswith .py or __init__.py)
    # - dotted module path: a.b -> <repo_root>/a/b.py or <repo_root>/a/b/__init__.py
    # - relative module ".x": require importer_file_path, resolve from package dir
    m = module.strip()
    if m.startswith("."):
        if not importer_file_path:
            return []
        base_dir = Path(importer_file_path).resolve().parent
        # For python relative imports, dots indicate going up; keep minimal: one-dot only.
        rel = m.lstrip(".").replace(".", "/")
        if not rel:
            return [str(base_dir / "__init__.py")]
        return [str(base_dir / f"{rel}.py"), str(base_dir / rel / "__init__.py")]
    if m.endswith(".py"):
        p = Path(m)
        return [str(p.resolve())] if p.is_absolute() else [str((Path(repo_root) / p).resolve())]
    rel = m.replace(".", "/")
    root = Path(repo_root).resolve()
    return [str((root / f"{rel}.py").resolve()), str((root / rel / "__init__.py").resolve())]


def _ts_module_candidates_abs(module: str, *, repo_root: str, importer_file_path: Optional[str]) -> List[str]:
    # Strict TS: relative only unless repo_root_hint + non-relative handled by caller.
    m = module.strip()
    if m.startswith("."):
        if not importer_file_path:
            return []
        base_dir = Path(importer_file_path).resolve().parent
        base = (base_dir / m).resolve()
        return [
            str(Path(f"{base}.ts")),
            str(Path(f"{base}.tsx")),
            str(Path(f"{base}.js")),
            str(base / "index.ts"),
            str(base / "index.tsx"),
            str(base / "index.js"),
        ]
    # Non-relative: without a package resolver, we cannot be strict.
    return []


def _resolve_import_python(
    *,
    store,
    rev: str,
    from_module: str,
    name: str,
    repo_root_hint: Optional[str],
    importer_file_path: Optional[str],
) -> Dict[str, Any]:
    if not repo_root_hint and not Path(from_module).is_absolute() and not from_module.endswith(".py"):
        return fail(
            "python resolve_import requires repo_root_hint for strict resolution when from_module is not an absolute file path",
            details={"from_module": from_module, "name": name},
        )
    repo_root = str(Path(repo_root_hint).resolve()) if repo_root_hint else str(Path("/").resolve())
    candidates = _python_module_candidates_abs(from_module, repo_root=repo_root, importer_file_path=importer_file_path)
    # Filter to files that exist at this rev.
    candidates = [p for p in candidates if file_exists_at_rev(store, rev=rev, file_path=p)]
    if not candidates:
        # best-effort: if repo_root_hint missing path normalization, try suffix matching (still strict on existence)
        if repo_root_hint and not Path(from_module).is_absolute() and not from_module.endswith(".py"):
            rel = from_module.replace(".", "/")
            suffixes = [f"/{rel}.py", f"/{rel}/__init__.py"]
            for suf in suffixes:
                matches = find_files_endingwith(store, rev=rev, suffix=suf, limit=20)
                candidates.extend(matches)
        candidates = list(dict.fromkeys(candidates))
    if not candidates:
        return fail("module file not found at rev", details={"rev": rev, "from_module": from_module, "candidates": candidates})

    results: List[Dict[str, Any]] = []
    for cpath in candidates:
        fv = file_version_blob(store, rev=rev, file_path=cpath)
        if not fv:
            continue
        _file_id, blob_hash, _lang = fv
        src = blob_content(store, blob_hash)
        if src is None:
            return fail(
                "blob content not available for strict python import resolution; index_repository(..., store_blobs=True) required",
                details={"file_path": cpath, "blob_hash": blob_hash},
            )
        exports = _python_module_exports(src, file_path=cpath)
        # Strict export:
        # - If name is bound at module scope -> ok
        # - Else if module has __all__ including name AND defines __getattr__ -> allow (lazy export pattern)
        #
        # NOTE: __all__ does NOT restrict `from module import name` in Python.
        # It only affects `from module import *`. Therefore we do not reject a name
        # just because it is not present in __all__.
        if name in exports["names"] or (exports["has_all"] and name in exports["all"] and exports["has_getattr"]):
            loc = exports["locs"].get(name)
            if loc is None:
                # fallback: still return module location as proof of export
                loc = exports["module_loc"]
            results.append(asdict(ImportHit(file_path=cpath, lang="python", import_text=f"from {from_module} import {name}", location=loc, resolved_path=cpath, resolved_symbol_id=None)))
            continue

        # Package semantics: from pkg import submodule will try pkg/submodule.py
        if cpath.endswith("/__init__.py") or cpath.endswith("\\__init__.py"):
            pkg_dir = str(Path(cpath).resolve().parent)
            sub_candidates = [
                str(Path(pkg_dir) / f"{name}.py"),
                str(Path(pkg_dir) / name / "__init__.py"),
            ]
            for sp in sub_candidates:
                if file_exists_at_rev(store, rev=rev, file_path=sp):
                    results.append(
                        asdict(
                            ImportHit(
                                file_path=sp,
                                lang="python",
                                import_text=f"from {from_module} import {name}",
                                location=Location(file_path=sp, start_line=1, start_col=1, end_line=1, end_col=1),
                                resolved_path=sp,
                                resolved_symbol_id=None,
                            )
                        )
                    )
                    break

    if not results:
        return fail(
            "import target not exported from module (strict)",
            details={"rev": rev, "lang": "python", "from_module": from_module, "name": name, "candidates_checked": candidates[:20]},
        )
    return ok({"rev": rev, "lang": "python", "from_module": from_module, "name": name, "matches": results})


def _python_module_exports(src: bytes, *, file_path: str) -> Dict[str, Any]:
    """Return module export info for strict Python resolution."""
    import ast

    text = src.decode("utf-8", errors="ignore")
    mod = ast.parse(text)

    names = set()
    locs: Dict[str, Location] = {}
    all_set = set()
    has_all = False
    has_getattr = False
    module_loc = Location(file_path=file_path, start_line=1, start_col=1, end_line=1, end_col=1)

    def add(name: str, node: ast.AST) -> None:
        names.add(name)
        lineno = getattr(node, "lineno", 1) or 1
        col = getattr(node, "col_offset", 0) or 0
        end_lineno = getattr(node, "end_lineno", lineno) or lineno
        end_col = getattr(node, "end_col_offset", col) or col
        locs[name] = Location(file_path=file_path, start_line=int(lineno), start_col=int(col + 1), end_line=int(end_lineno), end_col=int(end_col + 1))

    for stmt in mod.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if isinstance(stmt, ast.FunctionDef) and stmt.name == "__getattr__":
                has_getattr = True
            add(stmt.name, stmt)
        elif isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name):
                    if tgt.id == "__all__":
                        has_all = True
                        try:
                            v = ast.literal_eval(stmt.value)
                            if isinstance(v, (list, tuple)):
                                for s in v:
                                    if isinstance(s, str):
                                        all_set.add(s)
                        except Exception:
                            pass
                    else:
                        add(tgt.id, tgt)
        elif isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name):
                if stmt.target.id != "__all__":
                    add(stmt.target.id, stmt.target)
        elif isinstance(stmt, ast.Import):
            for alias in stmt.names:
                add(alias.asname or alias.name.split(".")[0], stmt)
        elif isinstance(stmt, ast.ImportFrom):
            for alias in stmt.names:
                if alias.name == "*":
                    continue
                add(alias.asname or alias.name, stmt)

    return {"names": names, "locs": locs, "has_all": has_all, "all": all_set, "has_getattr": has_getattr, "module_loc": module_loc}


def _resolve_import_ts(
    *,
    store,
    rev: str,
    from_module: str,
    name: str,
    repo_root_hint: Optional[str],
    importer_file_path: Optional[str],
    max_depth: int,
) -> Dict[str, Any]:
    if not repo_root_hint:
        # Without package resolution, strict TS requires repo_root_hint (and usually importer_file_path for relative).
        repo_root_hint = str(Path("/").resolve())
    candidates = _ts_module_candidates_abs(from_module, repo_root=str(Path(repo_root_hint).resolve()), importer_file_path=importer_file_path)
    candidates = [p for p in candidates if file_exists_at_rev(store, rev=rev, file_path=p)]
    if not candidates:
        return fail(
            "typescript module file not found at rev (strict). For relative imports, importer_file_path is required.",
            details={"rev": rev, "from_module": from_module, "importer_file_path": importer_file_path},
        )
    for cpath in candidates:
        fv = file_version_blob(store, rev=rev, file_path=cpath)
        if not fv:
            continue
        _file_id, blob_hash, _lang = fv
        src = blob_content(store, blob_hash)
        if src is None:
            return fail(
                "blob content not available for strict typescript export resolution; index_repository(..., store_blobs=True) required",
                details={"file_path": cpath, "blob_hash": blob_hash},
            )
        exports = _ts_collect_exports(store=store, rev=rev, file_path=cpath, source=src, max_depth=max_depth, visited=set())
        if name in exports["names"]:
            loc = exports["locs"].get(name) or Location(file_path=cpath, start_line=1, start_col=1, end_line=1, end_col=1)
            return ok(
                {
                    "rev": rev,
                    "lang": "typescript",
                    "from_module": from_module,
                    "name": name,
                    "matches": [
                        asdict(
                            ImportHit(
                                file_path=cpath,
                                lang="typescript",
                                import_text=f"import {{{name}}} from '{from_module}'",
                                location=loc,
                                resolved_path=cpath,
                                resolved_symbol_id=None,
                            )
                        )
                    ],
                }
            )
    return fail(
        "import target not exported from module (strict)",
        details={"rev": rev, "lang": "typescript", "from_module": from_module, "name": name, "candidates_checked": candidates[:20]},
    )


_TS_EXPORT_NAMED_FROM_RE = re.compile(r"export\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]")
_TS_EXPORT_STAR_FROM_RE = re.compile(r"export\s*\*\s*from\s*['\"]([^'\"]+)['\"]")
_TS_EXPORT_DECL_RE = re.compile(r"export\s+(?:async\s+)?(function|class|const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)")
_TS_EXPORT_LIST_RE = re.compile(r"export\s*\{([^}]+)\}\s*;?")


def _ts_collect_exports(
    *,
    store,
    rev: str,
    file_path: str,
    source: bytes,
    max_depth: int,
    visited: set,
) -> Dict[str, Any]:
    """Strict-ish export collector for common TS patterns. Unknown patterns are ignored (not guessed)."""
    key = (rev, file_path)
    if key in visited:
        return {"names": set(), "locs": {}}
    visited.add(key)
    if max_depth <= 0:
        return {"names": set(), "locs": {}}

    text = source.decode("utf-8", errors="ignore")
    names = set()
    locs: Dict[str, Location] = {}

    # Parse with tree-sitter to get accurate locations for export_statement nodes; use regex on node text for names.
    try:
        parser = create_parser("typescript")
        tree = parser.parse(source)
        root = tree.root_node
        stack = [root]
        export_nodes = []
        while stack:
            n = stack.pop()
            if n.type == "export_statement":
                export_nodes.append(n)
            stack.extend(reversed(n.children))
    except Exception:
        export_nodes = []

    def node_loc(n) -> Location:
        sl, sc = n.start_point
        el, ec = n.end_point
        return Location(file_path=file_path, start_line=sl + 1, start_col=sc + 1, end_line=el + 1, end_col=ec + 1)

    # Use export nodes if available; else fallback to line scanning.
    chunks: List[Tuple[str, Optional[Location]]] = []
    if export_nodes:
        for n in export_nodes:
            chunks.append((source[n.start_byte : n.end_byte].decode("utf-8", errors="ignore"), node_loc(n)))
    else:
        for line in text.splitlines():
            if "export" in line:
                chunks.append((line, None))

    for chunk, loc in chunks:
        m = _TS_EXPORT_DECL_RE.search(chunk)
        if m:
            nm = m.group(2)
            names.add(nm)
            if loc:
                locs[nm] = loc
            continue

        m = _TS_EXPORT_NAMED_FROM_RE.search(chunk)
        if m:
            spec = m.group(2)
            for part in m.group(1).split(","):
                part = part.strip()
                if not part:
                    continue
                if " as " in part:
                    _src, alias = [x.strip() for x in part.split(" as ", 1)]
                    nm = alias
                else:
                    nm = part
                # follow re-export
                sub = _resolve_import_ts(
                    store=store,
                    rev=rev,
                    from_module=spec,
                    name=nm,
                    repo_root_hint=str(Path(file_path).resolve().parents[0].parents[0]) if Path(file_path).is_absolute() else None,
                    importer_file_path=file_path,
                    max_depth=max_depth - 1,
                )
                if sub.get("ok"):
                    names.add(nm)
                    if loc:
                        locs[nm] = loc
            continue

        m = _TS_EXPORT_STAR_FROM_RE.search(chunk)
        if m:
            spec = m.group(1)
            # Strict: only include names we can prove by recursively parsing the target module.
            cand = _ts_module_candidates_abs(spec, repo_root=str(Path("/").resolve()), importer_file_path=file_path)
            cand = [p for p in cand if file_exists_at_rev(store, rev=rev, file_path=p)]
            for p in cand[:1]:
                fv = file_version_blob(store, rev=rev, file_path=p)
                if not fv:
                    continue
                _fid, bh, _lg = fv
                src2 = blob_content(store, bh)
                if not src2:
                    continue
                sub_exports = _ts_collect_exports(store=store, rev=rev, file_path=p, source=src2, max_depth=max_depth - 1, visited=visited)
                for nm in sub_exports["names"]:
                    names.add(nm)
                    if loc and nm not in locs:
                        locs[nm] = loc
            continue

        m = _TS_EXPORT_LIST_RE.search(chunk)
        if m:
            for part in m.group(1).split(","):
                part = part.strip()
                if not part:
                    continue
                if " as " in part:
                    _src, alias = [x.strip() for x in part.split(" as ", 1)]
                    nm = alias
                else:
                    nm = part
                names.add(nm)
                if loc:
                    locs[nm] = loc
            continue

    return {"names": names, "locs": locs}


def _resolve_import_go(*, store, rev: str, from_module: str, name: str, repo_root_hint: Optional[str]) -> Dict[str, Any]:
    """Strict (repo-local) Go import resolution.

    Assumptions for strict mode:
    - from_module is a repo-local package path (either absolute dir path or repo-relative dir)
    - name is an exported identifier expected to be defined in some file under that directory
    """
    if not repo_root_hint and not Path(from_module).is_absolute():
        return fail("go resolve_import requires repo_root_hint unless from_module is absolute path", details={"from_module": from_module})
    repo_root = str(Path(repo_root_hint).resolve()) if repo_root_hint else ""
    pkg_dir = str(Path(from_module).resolve()) if Path(from_module).is_absolute() else str((Path(repo_root) / from_module).resolve())
    # Go export convention: exported identifiers start with uppercase. If not, we still try but strict callers likely pass exported.
    # Find all files in this package dir at rev (by path prefix).
    cur = store.conn.cursor()
    cur.execute(
        """
        SELECT f.path
          FROM files f
          JOIN file_versions fv ON fv.file_id = f.file_id
         WHERE fv.rev = ? AND f.path LIKE ?
         LIMIT 500;
        """,
        (rev, f"{pkg_dir}/%"),
    )
    paths = [str(r[0]) for r in cur.fetchall() if str(r[0]).endswith(".go")]
    if not paths:
        return fail("go package directory not found at rev", details={"rev": rev, "pkg_dir": pkg_dir})
    matches: List[Dict[str, Any]] = []
    for p in paths:
        fv = file_version_blob(store, rev=rev, file_path=p)
        if not fv:
            continue
        file_id, blob_hash, _ = fv
        cur.execute(
            """
            SELECT symbol_id, name, kind, lang, start_line, start_col, end_line, end_col
              FROM symbols
             WHERE file_id=? AND blob_hash=? AND name=?
             LIMIT 10;
            """,
            (file_id, blob_hash, name),
        )
        for sid, sname, kind, slang, sl, sc, el, ec in cur.fetchall():
            matches.append(
                asdict(
                    SymbolHit(
                        symbol_id=str(sid),
                        name=str(sname),
                        kind=str(kind),
                        lang=str(slang),
                        location=Location(file_path=p, start_line=int(sl), start_col=int(sc), end_line=int(el), end_col=int(ec)),
                    )
                )
            )
    if not matches:
        return fail("go import target not found in package (strict repo-local)", details={"rev": rev, "pkg_dir": pkg_dir, "name": name})
    return ok({"rev": rev, "lang": "go", "from_module": from_module, "name": name, "matches": matches})


def _resolve_import_java(*, store, rev: str, from_module: str, name: str, repo_root_hint: Optional[str]) -> Dict[str, Any]:
    """Strict (repo-local) Java import resolution.

    from_module is a Java package or fully qualified class prefix.
    We map package to directory structure under repo_root_hint and search for class/interface definitions.
    """
    if not repo_root_hint:
        return fail("java resolve_import requires repo_root_hint for strict repo-local resolution", details={"from_module": from_module})
    repo_root = Path(repo_root_hint).resolve()
    pkg_path = from_module.replace(".", "/")
    # Search candidates: any file ending with /<pkg_path>/<name>.java
    suffix = f"/{pkg_path}/{name}.java"
    candidates = find_files_endingwith(store, rev=rev, suffix=suffix, limit=50)
    matches: List[Dict[str, Any]] = []
    for p in candidates:
        fv = file_version_blob(store, rev=rev, file_path=p)
        if not fv:
            continue
        file_id, blob_hash, _ = fv
        cur = store.conn.cursor()
        cur.execute(
            """
            SELECT symbol_id, name, kind, lang, start_line, start_col, end_line, end_col
              FROM symbols
             WHERE file_id=? AND blob_hash=? AND name=?
             LIMIT 10;
            """,
            (file_id, blob_hash, name),
        )
        for sid, sname, kind, slang, sl, sc, el, ec in cur.fetchall():
            matches.append(
                asdict(
                    SymbolHit(
                        symbol_id=str(sid),
                        name=str(sname),
                        kind=str(kind),
                        lang=str(slang),
                        location=Location(file_path=p, start_line=int(sl), start_col=int(sc), end_line=int(el), end_col=int(ec)),
                    )
                )
            )
    if not matches:
        return fail(
            "java import target not found in repo (strict repo-local)",
            details={"rev": rev, "from_module": from_module, "name": name, "suffix": suffix},
        )
    return ok({"rev": rev, "lang": "java", "from_module": from_module, "name": name, "matches": matches})


def _resolve_import_ruby(
    *,
    store,
    rev: str,
    from_module: str,
    name: str,
    repo_root_hint: Optional[str],
    importer_file_path: Optional[str],
) -> Dict[str, Any]:
    """Strict (repo-local) Ruby require/const resolution.

    We only support repo-local 'require_relative' style strict resolution:
    - from_module should be a relative path (like './foo' or 'foo/bar') or absolute path to a .rb file
    - name is a constant expected to be defined in that file (best-effort via symbols table)
    """
    if not repo_root_hint and not Path(from_module).is_absolute():
        return fail("ruby resolve_import requires repo_root_hint unless from_module is absolute path", details={"from_module": from_module})
    repo_root = str(Path(repo_root_hint).resolve()) if repo_root_hint else ""
    if Path(from_module).is_absolute():
        candidates = [str(Path(from_module).resolve())]
    else:
        base_dir = Path(importer_file_path).resolve().parent if importer_file_path else Path(repo_root)
        # normalize ./x, ../x, x/y
        mod = from_module
        if mod.startswith("./") or mod.startswith("../"):
            p = (base_dir / mod).resolve()
        else:
            p = (Path(repo_root) / mod).resolve()
        candidates = [str(p if str(p).endswith(".rb") else Path(f"{p}.rb"))]
    candidates = [p for p in candidates if file_exists_at_rev(store, rev=rev, file_path=p)]
    if not candidates:
        return fail("ruby required file not found at rev", details={"rev": rev, "from_module": from_module, "candidates": candidates})
    matches: List[Dict[str, Any]] = []
    for p in candidates:
        fv = file_version_blob(store, rev=rev, file_path=p)
        if not fv:
            continue
        file_id, blob_hash, _ = fv
        cur = store.conn.cursor()
        cur.execute(
            """
            SELECT symbol_id, name, kind, lang, start_line, start_col, end_line, end_col
              FROM symbols
             WHERE file_id=? AND blob_hash=? AND name=?
             LIMIT 10;
            """,
            (file_id, blob_hash, name),
        )
        for sid, sname, kind, slang, sl, sc, el, ec in cur.fetchall():
            matches.append(
                asdict(
                    SymbolHit(
                        symbol_id=str(sid),
                        name=str(sname),
                        kind=str(kind),
                        lang=str(slang),
                        location=Location(file_path=p, start_line=int(sl), start_col=int(sc), end_line=int(el), end_col=int(ec)),
                    )
                )
            )
    if not matches:
        return fail("ruby constant not found in required file (strict repo-local)", details={"rev": rev, "file": candidates[0], "name": name})
    return ok({"rev": rev, "lang": "ruby", "from_module": from_module, "name": name, "matches": matches})


# ----------------------------
# CPG queries (SQLite edges/calls)
# ----------------------------


DEFAULT_EDGE_KINDS: Tuple[str, ...] = ("DDG", "CFG", "CFG_BRANCH", "CALL", "CFG_IP_CALL", "CFG_IP_RET")


def cpg_slice(
    *,
    db_path: str,
    rev: Optional[str] = None,
    criteria_node_ids: Sequence[str],
    direction: str,
    edge_kinds: Sequence[str] = DEFAULT_EDGE_KINDS,
    max_nodes: int = 200,
) -> Dict[str, Any]:
    """Graph slice over edges table. direction: 'forward'|'backward'."""
    if direction not in {"forward", "backward"}:
        return fail("invalid direction", details={"direction": direction})
    return _bfs_paths(
        db_path=db_path,
        rev=rev,
        starts=list(criteria_node_ids),
        direction="out" if direction == "forward" else "in",
        edge_kinds=edge_kinds,
        max_nodes=max_nodes,
        stop_at=None,
    )


def cpg_query_forward(
    *,
    db_path: str,
    rev: Optional[str] = None,
    start_node_id: str,
    edge_kinds: Sequence[str] = DEFAULT_EDGE_KINDS,
    max_steps: int = 64,
    max_visited: int = 2000,
) -> Dict[str, Any]:
    return _bfs_paths(
        db_path=db_path,
        rev=rev,
        starts=[start_node_id],
        direction="out",
        edge_kinds=edge_kinds,
        max_nodes=max_visited,
        max_steps=max_steps,
        stop_at=None,
    )


def cpg_query_backward(
    *,
    db_path: str,
    rev: Optional[str] = None,
    sink_node_id: str,
    edge_kinds: Sequence[str] = DEFAULT_EDGE_KINDS,
    max_steps: int = 64,
    max_visited: int = 2000,
) -> Dict[str, Any]:
    return _bfs_paths(
        db_path=db_path,
        rev=rev,
        starts=[sink_node_id],
        direction="in",
        edge_kinds=edge_kinds,
        max_nodes=max_visited,
        max_steps=max_steps,
        stop_at=None,
    )


def cpg_reachability(
    *,
    db_path: str,
    rev: Optional[str] = None,
    src_node_id: str,
    dst_node_id: str,
    edge_kinds: Sequence[str] = DEFAULT_EDGE_KINDS,
    max_steps: int = 128,
) -> Dict[str, Any]:
    """Return a best-effort shortest path from src to dst."""
    return _bfs_paths(
        db_path=db_path,
        rev=rev,
        starts=[src_node_id],
        direction="out",
        edge_kinds=edge_kinds,
        max_nodes=5000,
        max_steps=max_steps,
        stop_at=dst_node_id,
    )


def cpg_callgraph(
    *,
    db_path: str,
    rev: Optional[str] = None,
    node_or_symbol: str,
    direction: str = "out",
    depth: int = 2,
    limit: int = 200,
) -> Dict[str, Any]:
    """Call graph neighborhood using CALL/CFG_IP_* edges (best-effort)."""
    edge_kinds = ("CALL", "CFG_IP_CALL", "CFG_IP_RET")
    store = open_store(db_path)
    try:
        r = require_rev(store, rev)
        start = node_or_symbol
        # If caller passes a function symbol_id, use its callsites as seeds (best effort).
        if ":" in node_or_symbol and "-" in node_or_symbol:
            # Use this symbol_id as a node id directly if present; otherwise, fallback to name-based callsites.
            start = node_or_symbol
        frontier = [start]
        visited = {start}
        edges_out: List[Tuple[str, str, str]] = []
        for _ in range(max(0, int(depth))):
            nxt: List[str] = []
            for nid in frontier:
                for src, dst, kind in iter_edges_for_rev(
                    store, rev=r, direction=direction, node_id=nid, kinds=edge_kinds, limit=limit
                ):
                    edges_out.append((src, dst, kind))
                    other = dst if direction == "out" else src
                    if other not in visited:
                        visited.add(other)
                        nxt.append(other)
            frontier = nxt
            if not frontier:
                break
        locs = node_locations(store, list(visited))
        node_map = []
        for nid, loc in zip(list(visited), locs):
            if loc:
                node_map.append(asdict(NodeHit(node_id=nid, kind="node", location=loc)))
        return ok({"rev": r, "nodes": node_map, "edges": [{"src": a, "dst": b, "kind": k} for a, b, k in edges_out]})
    except Exception as e:
        return fail("cpg_callgraph failed", details={"error": str(e)})
    finally:
        store.close()


def cpg_cfg_region(
    *,
    db_path: str,
    rev: Optional[str] = None,
    root_node_id: str,
    depth: int = 2,
    limit: int = 500,
) -> Dict[str, Any]:
    """Return a local CFG region around a control node (best-effort)."""
    store = open_store(db_path)
    try:
        r = require_rev(store, rev)
        edge_kinds = ("CFG", "CFG_BRANCH")
        frontier = [root_node_id]
        visited = {root_node_id}
        edges_out: List[Tuple[str, str, str]] = []
        for _ in range(max(0, int(depth))):
            nxt: List[str] = []
            for nid in frontier:
                for src, dst, kind in iter_edges_for_rev(store, rev=r, direction="out", node_id=nid, kinds=edge_kinds, limit=limit):
                    edges_out.append((src, dst, kind))
                    if dst not in visited:
                        visited.add(dst)
                        nxt.append(dst)
            frontier = nxt
            if not frontier:
                break
        locs = node_locations(store, list(visited))
        nodes = []
        for nid, loc in zip(list(visited), locs):
            if loc:
                nodes.append(asdict(NodeHit(node_id=nid, kind="cfg_node", location=loc)))
        return ok({"rev": r, "nodes": nodes, "edges": [{"src": a, "dst": b, "kind": k} for a, b, k in edges_out]})
    except Exception as e:
        return fail("cpg_cfg_region failed", details={"error": str(e)})
    finally:
        store.close()


def _bfs_paths(
    *,
    db_path: str,
    rev: Optional[str],
    starts: List[str],
    direction: str,
    edge_kinds: Sequence[str],
    max_nodes: int,
    max_steps: int = 64,
    stop_at: Optional[str],
) -> Dict[str, Any]:
    store = open_store(db_path)
    try:
        r = require_rev(store, rev)
        from collections import deque

        q = deque()
        parent: Dict[str, Optional[str]] = {}
        parent_edge: Dict[str, Optional[str]] = {}
        for s in starts:
            parent[s] = None
            parent_edge[s] = None
            q.append((s, 0))

        visited = set(starts)
        found = None

        while q and len(visited) < int(max_nodes):
            node, steps = q.popleft()
            if stop_at and node == stop_at:
                found = node
                break
            if steps >= int(max_steps):
                continue
            edges = iter_edges_for_rev(store, rev=r, direction=direction, node_id=node, kinds=edge_kinds, limit=500)
            for src, dst, kind in edges:
                nxt = dst if direction == "out" else src
                if nxt in visited:
                    continue
                visited.add(nxt)
                parent[nxt] = node
                parent_edge[nxt] = kind
                q.append((nxt, steps + 1))

        # If reachability, reconstruct shortest path; else return visited set.
        if stop_at:
            if found is None and stop_at in parent:
                found = stop_at
            if found is None:
                return ok({"rev": r, "reachable": False, "path": None})
            path_nodes: List[str] = []
            edge_kinds_path: List[str] = []
            cur = found
            while cur is not None:
                path_nodes.append(cur)
                ek = parent_edge.get(cur)
                if ek:
                    edge_kinds_path.append(ek)
                cur = parent.get(cur)
            path_nodes.reverse()
            edge_kinds_path.reverse()
            locs = node_locations(store, path_nodes)
            locs_out = [asdict(l) for l in locs if l is not None]
            return ok(
                {
                    "rev": r,
                    "reachable": True,
                    "path": asdict(PathResult(node_ids=path_nodes, edge_kinds=edge_kinds_path, locations=[l for l in locs if l])),
                }
            )

        # slice/query: return visited nodes + their locations
        nodes = []
        locs = node_locations(store, list(visited))
        for nid, loc in zip(list(visited), locs):
            if not loc:
                continue
            nodes.append(asdict(NodeHit(node_id=nid, kind="node", location=loc)))
        return ok({"rev": r, "nodes": nodes, "count": len(nodes)})
    except Exception as e:
        return fail("cpg graph query failed", details={"error": str(e)})
    finally:
        store.close()


# ----------------------------
# Summary
# ----------------------------


def cpg_summary(
    *,
    db_path: str,
    rev: Optional[str] = None,
    symbol: str,
) -> Dict[str, Any]:
    """Summarize a function/class/module symbol with deterministic evidence."""
    store = open_store(db_path)
    try:
        r = require_rev(store, rev)

        sym_row = symbol_row_at_rev(store, rev=r, symbol_id=symbol) if (":" in symbol and "-" in symbol) else None
        if sym_row is None:
            # treat as name -> first match
            sids = store.resolve_symbol_ids(symbol, limit=1)
            if not sids:
                return fail("symbol not found", details={"rev": r, "symbol": symbol})
            sym_row = symbol_row_at_rev(store, rev=r, symbol_id=sids[0])
            if sym_row is None:
                return fail("symbol not found at rev", details={"rev": r, "symbol": symbol})

        cur = store.conn.cursor()
        cur.execute(
            """
            SELECT signature, summary_text, summary_struct, generator, llm_model
              FROM repomap_symbols
             WHERE symbol_id=?
             LIMIT 1;
            """,
            (sym_row["symbol_id"],),
        )
        row = cur.fetchone()
        if row:
            signature, summary_text, summary_struct, generator, llm_model = row
            try:
                struct = json.loads(summary_struct) if summary_struct else {}
            except Exception:
                struct = {}
            return ok(
                {
                    "rev": r,
                    "symbol_id": sym_row["symbol_id"],
                    "name": sym_row["name"],
                    "kind": sym_row["kind"],
                    "lang": sym_row["lang"],
                    "file_path": sym_row["file_path"],
                    "location": asdict(sym_row["location"]),
                    "signature": str(signature),
                    "summary_text": str(summary_text),
                    "summary_struct": struct,
                    "_meta": {"generator": generator, "llm_model": llm_model},
                }
            )

        # Fallback: deterministic, best-effort summary from source snippet.
        src = blob_content(store, sym_row["blob_hash"])
        if src is None:
            return ok(
                {
                    "rev": r,
                    "symbol_id": sym_row["symbol_id"],
                    "name": sym_row["name"],
                    "kind": sym_row["kind"],
                    "lang": sym_row["lang"],
                    "file_path": sym_row["file_path"],
                    "location": asdict(sym_row["location"]),
                    "signature": _signature_for_symbol_row(store, sym_row),
                    "summary_text": "",
                    "summary_struct": {},
                    "_meta": {"generator": "none", "note": "blob content not available; index_repository(..., store_blobs=True) recommended"},
                }
            )

        start_b = int(sym_row["start_byte"])
        end_b = int(sym_row["end_byte"])
        snippet = src[start_b:end_b].decode("utf-8", errors="ignore")
        signature = _signature_for_symbol_row(store, sym_row)
        summary_text, summary_struct = _heuristic_summary(sym_row["lang"], snippet)

        return ok(
            {
                "rev": r,
                "symbol_id": sym_row["symbol_id"],
                "name": sym_row["name"],
                "kind": sym_row["kind"],
                "lang": sym_row["lang"],
                "file_path": sym_row["file_path"],
                "location": asdict(sym_row["location"]),
                "signature": signature,
                "summary_text": summary_text,
                "summary_struct": summary_struct,
                "_meta": {"generator": "heuristic"},
            }
        )
    except Exception as e:
        return fail("cpg_summary failed", details={"error": str(e)})
    finally:
        store.close()


_RAISE_RE = re.compile(r"\braise\b|\bthrow\b")
_RETURN_RE = re.compile(r"\breturn\b")
_SIDE_EFFECT_RE = re.compile(r"\b(open|write|delete|remove|unlink|exec|eval|requests\\.|http|socket|connect|commit|rollback)\\b")


def _heuristic_summary(lang: str, snippet: str) -> Tuple[str, Dict[str, Any]]:
    text = snippet.strip()
    first_line = text.splitlines()[0].strip() if text else ""
    has_return = bool(_RETURN_RE.search(text))
    may_throw = bool(_RAISE_RE.search(text))
    side_effect = bool(_SIDE_EFFECT_RE.search(text.lower()))
    struct = {
        "first_line": first_line,
        "has_return": has_return,
        "may_throw": may_throw,
        "has_side_effects": side_effect,
    }
    summary = first_line
    return summary, struct


