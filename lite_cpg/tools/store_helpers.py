"""SQLite-backed helpers for repo-scale tools.

All helpers are read-only and designed to support multi-revision queries:
- A revision (rev) selects a file->blob_hash mapping via file_versions.
- nodes/edges/symbols/calls are stored by (file_id, blob_hash).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..store.backends.sqlite import LiteCPGStore
from .models import Location


def open_store(db_path: str) -> LiteCPGStore:
    return LiteCPGStore(Path(db_path))


def get_latest_rev(store: LiteCPGStore) -> Optional[str]:
    cur = store.conn.cursor()
    cur.execute("SELECT rev FROM revisions ORDER BY created_at DESC LIMIT 1;")
    row = cur.fetchone()
    return row[0] if row else None


def require_rev(store: LiteCPGStore, rev: Optional[str]) -> str:
    if rev:
        cur = store.conn.cursor()
        cur.execute("SELECT 1 FROM revisions WHERE rev=? LIMIT 1;", (rev,))
        if cur.fetchone() is None:
            raise ValueError(f"Unknown rev: {rev}")
        return rev
    latest = get_latest_rev(store)
    if not latest:
        raise ValueError("No revisions found. Run index_repository(...) first.")
    return latest


def file_id_for_path(store: LiteCPGStore, path: str) -> Optional[int]:
    cur = store.conn.cursor()
    cur.execute("SELECT file_id FROM files WHERE path=? LIMIT 1;", (path,))
    row = cur.fetchone()
    return int(row[0]) if row else None


def file_version_blob(store: LiteCPGStore, *, rev: str, file_path: str) -> Optional[Tuple[int, str, str]]:
    """Return (file_id, blob_hash, lang) for a file at a revision."""
    cur = store.conn.cursor()
    cur.execute(
        """
        SELECT f.file_id, fv.blob_hash, f.lang
          FROM files f
          JOIN file_versions fv ON fv.file_id = f.file_id
         WHERE f.path = ? AND fv.rev = ?
         LIMIT 1;
        """,
        (file_path, rev),
    )
    row = cur.fetchone()
    if not row:
        return None
    return (int(row[0]), str(row[1]), str(row[2]))


def file_exists_at_rev(store: LiteCPGStore, *, rev: str, file_path: str) -> bool:
    cur = store.conn.cursor()
    cur.execute(
        """
        SELECT 1
          FROM files f
          JOIN file_versions fv ON fv.file_id = f.file_id
         WHERE fv.rev = ? AND f.path = ?
         LIMIT 1;
        """,
        (rev, file_path),
    )
    return cur.fetchone() is not None


def find_files_endingwith(store: LiteCPGStore, *, rev: str, suffix: str, limit: int = 50) -> List[str]:
    """Find absolute file paths in a revision ending with suffix (best-effort helper)."""
    cur = store.conn.cursor()
    cur.execute(
        """
        SELECT f.path
          FROM files f
          JOIN file_versions fv ON fv.file_id = f.file_id
         WHERE fv.rev = ? AND f.path LIKE ?
         LIMIT ?;
        """,
        (rev, f"%{suffix}", int(limit)),
    )
    return [str(r[0]) for r in cur.fetchall()]


def blob_content(store: LiteCPGStore, blob_hash: str) -> Optional[bytes]:
    cur = store.conn.cursor()
    cur.execute("SELECT compressed, content FROM blobs WHERE blob_hash=? LIMIT 1;", (blob_hash,))
    row = cur.fetchone()
    if not row:
        return None
    compressed, payload = int(row[0]), row[1]
    if compressed:
        import zlib

        return zlib.decompress(payload)
    return payload


def node_location(store: LiteCPGStore, node_id: str) -> Optional[Location]:
    cur = store.conn.cursor()
    cur.execute(
        """
        SELECT f.path, n.start_line, n.start_col, n.end_line, n.end_col
          FROM nodes n
          JOIN files f ON f.file_id = n.file_id
         WHERE n.node_id = ?
         LIMIT 1;
        """,
        (node_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return Location(file_path=str(row[0]), start_line=int(row[1]), start_col=int(row[2]), end_line=int(row[3]), end_col=int(row[4]))


def symbol_location(store: LiteCPGStore, symbol_id: str) -> Optional[Tuple[str, Location, Dict[str, Any]]]:
    """Return (lang, location, attrs) for symbol_id."""
    cur = store.conn.cursor()
    cur.execute(
        """
        SELECT f.path, s.lang, s.start_line, s.start_col, s.end_line, s.end_col, s.attrs
          FROM symbols s
          JOIN files f ON f.file_id = s.file_id
         WHERE s.symbol_id = ?
         LIMIT 1;
        """,
        (symbol_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    path, lang, sl, sc, el, ec, attrs = row
    try:
        attrs_dict = json.loads(attrs) if attrs else {}
    except Exception:
        attrs_dict = {}
    return (
        str(lang),
        Location(file_path=str(path), start_line=int(sl), start_col=int(sc), end_line=int(el), end_col=int(ec)),
        attrs_dict,
    )


def symbol_row_at_rev(store: LiteCPGStore, *, rev: str, symbol_id: str) -> Optional[Dict[str, Any]]:
    """Fetch symbol row for a specific rev (ensures file_versions match)."""
    cur = store.conn.cursor()
    cur.execute(
        """
        SELECT f.path, f.lang, fv.blob_hash,
               s.symbol_id, s.kind, s.name,
               s.start_byte, s.end_byte, s.start_line, s.start_col, s.end_line, s.end_col, s.attrs
          FROM symbols s
          JOIN files f ON f.file_id = s.file_id
          JOIN file_versions fv ON fv.file_id = s.file_id AND fv.blob_hash = s.blob_hash
         WHERE fv.rev = ? AND s.symbol_id = ?
         LIMIT 1;
        """,
        (rev, symbol_id),
    )
    row = cur.fetchone()
    if not row:
        return None
    (
        path,
        lang,
        blob_hash,
        sid,
        kind,
        name,
        start_b,
        end_b,
        sl,
        sc,
        el,
        ec,
        attrs,
    ) = row
    try:
        attrs_dict = json.loads(attrs) if attrs else {}
    except Exception:
        attrs_dict = {}
    return {
        "file_path": str(path),
        "lang": str(lang),
        "blob_hash": str(blob_hash),
        "symbol_id": str(sid),
        "kind": str(kind),
        "name": str(name),
        "start_byte": int(start_b),
        "end_byte": int(end_b),
        "location": Location(file_path=str(path), start_line=int(sl), start_col=int(sc), end_line=int(el), end_col=int(ec)),
        "attrs": attrs_dict,
    }


def iter_edges_for_rev(
    store: LiteCPGStore,
    *,
    rev: str,
    direction: str,
    node_id: str,
    kinds: Optional[Sequence[str]] = None,
    limit: int = 500,
) -> List[Tuple[str, str, str]]:
    """Return [(src, dst, kind)] edges for node_id at rev."""
    if direction not in {"out", "in"}:
        raise ValueError("direction must be 'out' or 'in'")
    cur = store.conn.cursor()
    params: List[Any] = [rev, node_id]
    kind_clause = ""
    if kinds:
        placeholders = ",".join(["?"] * len(kinds))
        kind_clause = f" AND e.kind IN ({placeholders})"
        params.extend(list(kinds))
    params.append(int(limit))
    if direction == "out":
        cur.execute(
            f"""
            SELECT e.src, e.dst, e.kind
              FROM edges e
              JOIN file_versions fv ON fv.file_id = e.file_id AND fv.blob_hash = e.blob_hash
             WHERE fv.rev = ? AND e.src = ? {kind_clause}
             LIMIT ?;
            """,
            tuple(params),
        )
    else:
        cur.execute(
            f"""
            SELECT e.src, e.dst, e.kind
              FROM edges e
              JOIN file_versions fv ON fv.file_id = e.file_id AND fv.blob_hash = e.blob_hash
             WHERE fv.rev = ? AND e.dst = ? {kind_clause}
             LIMIT ?;
            """,
            tuple(params),
        )
    return [(str(a), str(b), str(k)) for (a, b, k) in cur.fetchall()]


def node_locations(store: LiteCPGStore, node_ids: Sequence[str]) -> List[Optional[Location]]:
    if not node_ids:
        return []
    cur = store.conn.cursor()
    placeholders = ",".join(["?"] * len(node_ids))
    cur.execute(
        f"""
        SELECT n.node_id, f.path, n.start_line, n.start_col, n.end_line, n.end_col
          FROM nodes n
          JOIN files f ON f.file_id = n.file_id
         WHERE n.node_id IN ({placeholders});
        """,
        tuple(node_ids),
    )
    by_id: Dict[str, Location] = {}
    for nid, path, sl, sc, el, ec in cur.fetchall():
        by_id[str(nid)] = Location(
            file_path=str(path),
            start_line=int(sl),
            start_col=int(sc),
            end_line=int(el),
            end_col=int(ec),
        )
    return [by_id.get(nid) for nid in node_ids]


