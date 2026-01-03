"""SQLite persistence for repository-scale Lite-CPG.

Goals:
- Persist nodes/edges/symbols/calls for fast retrieval and slicing.
- Support repository revisions (e.g. PR head) with file->blob_hash mapping.
- Enable incremental updates by reusing existing blob_hash artifacts.

This is intentionally dependency-light (stdlib sqlite3) to fit CI / offline usage.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ...core.builder import ParsedFile
from ...core.cpg import Edge, LiteCPG, Node, Symbol
from ...core.languages import create_parser, normalize_lang
from ...repo.scan import RepoScanConfig, scan_repo
from ...repo.versioning import content_hash


SCHEMA_VERSION = 1


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class StorePaths:
    root: Path
    db: Path


@dataclass(frozen=True)
class _FileEntry:
    path: Path
    lang: str
    file_id: int
    blob_hash: str
    size_bytes: int


def default_store_paths(repo_root: Path) -> StorePaths:
    root = repo_root / ".lite_cpg"
    return StorePaths(root=root, db=root / "cpg.sqlite")


class LiteCPGStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self._ensure_schema()

    def close(self) -> None:
        self.conn.close()

    def _ensure_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        )
        cur.execute(
            "INSERT OR IGNORE INTO meta(key,value) VALUES('schema_version', ?);",
            (str(SCHEMA_VERSION),),
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS revisions(
              rev TEXT PRIMARY KEY,
              base_rev TEXT,
              created_at REAL NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS files(
              file_id INTEGER PRIMARY KEY AUTOINCREMENT,
              path TEXT NOT NULL UNIQUE,
              lang TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS file_versions(
              rev TEXT NOT NULL,
              file_id INTEGER NOT NULL,
              blob_hash TEXT NOT NULL,
              size INTEGER NOT NULL,
              mtime REAL NOT NULL,
              PRIMARY KEY(rev, file_id),
              FOREIGN KEY(rev) REFERENCES revisions(rev) ON DELETE CASCADE,
              FOREIGN KEY(file_id) REFERENCES files(file_id) ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS blobs(
              blob_hash TEXT PRIMARY KEY,
              compressed INTEGER NOT NULL,
              content BLOB NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS nodes(
              node_id TEXT PRIMARY KEY,
              blob_hash TEXT NOT NULL,
              file_id INTEGER NOT NULL,
              lang TEXT NOT NULL,
              kind TEXT NOT NULL,
              start_byte INTEGER NOT NULL,
              end_byte INTEGER NOT NULL,
              start_line INTEGER NOT NULL,
              start_col INTEGER NOT NULL,
              end_line INTEGER NOT NULL,
              end_col INTEGER NOT NULL,
              attrs TEXT NOT NULL,
              FOREIGN KEY(file_id) REFERENCES files(file_id) ON DELETE CASCADE
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_nodes_blob ON nodes(blob_hash);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_id);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS edges(
              blob_hash TEXT NOT NULL,
              file_id INTEGER NOT NULL,
              src TEXT NOT NULL,
              dst TEXT NOT NULL,
              kind TEXT NOT NULL,
              attrs TEXT NOT NULL,
              FOREIGN KEY(file_id) REFERENCES files(file_id) ON DELETE CASCADE
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src, kind);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst, kind);")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS symbols(
              symbol_id TEXT PRIMARY KEY,
              blob_hash TEXT NOT NULL,
              file_id INTEGER NOT NULL,
              lang TEXT NOT NULL,
              kind TEXT NOT NULL,
              name TEXT NOT NULL,
              start_byte INTEGER NOT NULL,
              end_byte INTEGER NOT NULL,
              start_line INTEGER NOT NULL,
              start_col INTEGER NOT NULL,
              end_line INTEGER NOT NULL,
              end_col INTEGER NOT NULL,
              attrs TEXT NOT NULL,
              FOREIGN KEY(file_id) REFERENCES files(file_id) ON DELETE CASCADE
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sym_name ON symbols(name, lang);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sym_blob ON symbols(blob_hash);")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS calls(
              blob_hash TEXT NOT NULL,
              file_id INTEGER NOT NULL,
              src_node TEXT NOT NULL,
              dst_name TEXT NOT NULL,
              dst_symbol TEXT,
              resolved INTEGER NOT NULL,
              attrs TEXT NOT NULL,
              FOREIGN KEY(file_id) REFERENCES files(file_id) ON DELETE CASCADE
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_calls_unres ON calls(dst_name, resolved);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_calls_src ON calls(src_node);")

        # Placeholder for future RepoMap/DeepWiki-style summaries.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS repomap_files(
              blob_hash TEXT NOT NULL,
              file_id INTEGER NOT NULL,
              path TEXT NOT NULL,
              lang TEXT NOT NULL,
              generator TEXT NOT NULL,
              llm_model TEXT NOT NULL,
              file_summary TEXT NOT NULL,
              hash TEXT NOT NULL,
              PRIMARY KEY(blob_hash, file_id),
              FOREIGN KEY(file_id) REFERENCES files(file_id) ON DELETE CASCADE
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_repomap_files_path ON repomap_files(path);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS repomap_symbols(
              symbol_id TEXT PRIMARY KEY,
              blob_hash TEXT NOT NULL,
              file_id INTEGER NOT NULL,
              lang TEXT NOT NULL,
              kind TEXT NOT NULL,
              name TEXT NOT NULL,
              start_line INTEGER NOT NULL,
              start_col INTEGER NOT NULL,
              end_line INTEGER NOT NULL,
              end_col INTEGER NOT NULL,
              signature TEXT NOT NULL,
              summary_struct TEXT NOT NULL,
              summary_text TEXT NOT NULL,
              hash TEXT NOT NULL,
              generator TEXT NOT NULL,
              llm_model TEXT NOT NULL,
              FOREIGN KEY(file_id) REFERENCES files(file_id) ON DELETE CASCADE
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_repomap_sym_name ON repomap_symbols(name, lang);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_repomap_sym_blob ON repomap_symbols(blob_hash);")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS repomap_packages(
              rev TEXT NOT NULL,
              package_path TEXT NOT NULL,
              summary TEXT NOT NULL,
              hash TEXT NOT NULL,
              generator TEXT NOT NULL,
              llm_model TEXT NOT NULL,
              PRIMARY KEY(rev, package_path),
              FOREIGN KEY(rev) REFERENCES revisions(rev) ON DELETE CASCADE
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS repomap_runs(
              rev TEXT NOT NULL,
              created_at REAL NOT NULL,
              duration_s REAL NOT NULL,
              generator TEXT NOT NULL,
              llm_model TEXT NOT NULL,
              llm_requests INTEGER NOT NULL,
              prompt_tokens INTEGER NOT NULL,
              completion_tokens INTEGER NOT NULL,
              total_tokens INTEGER NOT NULL,
              llm_time_s REAL NOT NULL,
              PRIMARY KEY(rev, generator, llm_model),
              FOREIGN KEY(rev) REFERENCES revisions(rev) ON DELETE CASCADE
            );
            """
        )

        # Backward-compatible migrations for existing DBs.
        for ddl in [
            "ALTER TABLE repomap_files ADD COLUMN generator TEXT NOT NULL DEFAULT 'heuristic';",
            "ALTER TABLE repomap_files ADD COLUMN llm_model TEXT NOT NULL DEFAULT '';",
            "ALTER TABLE repomap_symbols ADD COLUMN generator TEXT NOT NULL DEFAULT 'heuristic';",
            "ALTER TABLE repomap_symbols ADD COLUMN llm_model TEXT NOT NULL DEFAULT '';",
            "ALTER TABLE repomap_packages ADD COLUMN generator TEXT NOT NULL DEFAULT 'heuristic';",
            "ALTER TABLE repomap_packages ADD COLUMN llm_model TEXT NOT NULL DEFAULT '';",
        ]:
            try:
                cur.execute(ddl)
            except sqlite3.OperationalError:
                pass

        # Best-effort full-text search over code (optional; works if sqlite has FTS5).
        try:
            cur.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS fts_code USING fts5(
                  path, lang, content, blob_hash UNINDEXED
                );
                """
            )
        except sqlite3.OperationalError:
            # FTS5 not available; skip.
            pass

        self.conn.commit()

    def begin_revision(self, rev: str, base_rev: Optional[str] = None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO revisions(rev, base_rev, created_at) VALUES(?,?,?);",
            (rev, base_rev, time.time()),
        )

    def upsert_file(self, path: str, lang: str) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO files(path, lang) VALUES(?,?) ON CONFLICT(path) DO UPDATE SET lang=excluded.lang;",
            (path, lang),
        )
        cur.execute("SELECT file_id FROM files WHERE path=?;", (path,))
        row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def upsert_file_version(self, rev: str, file_id: int, blob_hash: str, size: int, mtime: float) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO file_versions(rev, file_id, blob_hash, size, mtime)
            VALUES(?,?,?,?,?);
            """,
            (rev, file_id, blob_hash, int(size), float(mtime)),
        )

    def upsert_blob(self, blob_hash: str, content: bytes, compress: bool = True) -> None:
        compressed = 1 if compress else 0
        payload = zlib.compress(content, 6) if compress else content
        self.conn.execute(
            "INSERT OR IGNORE INTO blobs(blob_hash, compressed, content) VALUES(?,?,?);",
            (blob_hash, compressed, payload),
        )

    def has_blob_artifacts(self, blob_hash: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM nodes WHERE blob_hash=? LIMIT 1;", (blob_hash,))
        return cur.fetchone() is not None

    def put_file_artifacts(
        self,
        file_id: int,
        blob_hash: str,
        lang: str,
        nodes: Sequence[Node],
        edges: Sequence[Edge],
        symbols: Sequence[Symbol],
        calls: Sequence[Tuple[str, str, Optional[str], int, Dict[str, str]]],
        path: str,
        source_text: Optional[str] = None,
    ) -> None:
        cur = self.conn.cursor()

        cur.executemany(
            """
            INSERT OR IGNORE INTO nodes(
              node_id, blob_hash, file_id, lang, kind,
              start_byte, end_byte, start_line, start_col, end_line, end_col, attrs
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?);
            """,
            [
                (
                    n.id,
                    blob_hash,
                    file_id,
                    lang,
                    n.kind,
                    int(n.attrs.get("start_byte", "0")),
                    int(n.attrs.get("end_byte", "0")),
                    n.span[1],
                    n.span[2],
                    n.span[3],
                    n.span[4],
                    _json(n.attrs),
                )
                for n in nodes
            ],
        )

        cur.executemany(
            "INSERT INTO edges(blob_hash, file_id, src, dst, kind, attrs) VALUES(?,?,?,?,?,?);",
            [(blob_hash, file_id, e.src, e.dst, e.kind, _json(e.attrs)) for e in edges],
        )

        sym_rows = []
        for s in symbols:
            start_b, end_b = _range_from_id(s.id)
            sym_rows.append(
                (
                    s.id,
                    blob_hash,
                    file_id,
                    s.lang,
                    s.kind,
                    s.name,
                    start_b,
                    end_b,
                    s.span[1],
                    s.span[2],
                    s.span[3],
                    s.span[4],
                    _json({}),
                )
            )
        cur.executemany(
            """
            INSERT OR REPLACE INTO symbols(
              symbol_id, blob_hash, file_id, lang, kind, name,
              start_byte, end_byte, start_line, start_col, end_line, end_col, attrs
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?);
            """,
            sym_rows,
        )

        cur.executemany(
            """
            INSERT INTO calls(blob_hash, file_id, src_node, dst_name, dst_symbol, resolved, attrs)
            VALUES(?,?,?,?,?,?,?);
            """,
            [
                (
                    blob_hash,
                    file_id,
                    src_node,
                    dst_name,
                    dst_symbol,
                    int(resolved),
                    _json(attrs),
                )
                for (src_node, dst_name, dst_symbol, resolved, attrs) in calls
            ],
        )

        if source_text is not None:
            try:
                cur.execute(
                    "INSERT INTO fts_code(path, lang, content, blob_hash) VALUES(?,?,?,?);",
                    (path, lang, source_text, blob_hash),
                )
            except sqlite3.OperationalError:
                pass

    def resolve_calls(self, lang: Optional[str] = None) -> None:
        """Resolve calls by name to a symbol_id (best-effort) and materialize CFG_IP edges."""
        cur = self.conn.cursor()
        if lang:
            cur.execute(
                """
                UPDATE calls
                   SET dst_symbol = (
                     SELECT s.symbol_id FROM symbols s
                      WHERE s.name = calls.dst_name AND s.lang = ?
                      ORDER BY s.symbol_id ASC LIMIT 1
                   ),
                       resolved = CASE WHEN (
                         SELECT s.symbol_id FROM symbols s
                          WHERE s.name = calls.dst_name AND s.lang = ?
                          ORDER BY s.symbol_id ASC LIMIT 1
                       ) IS NULL THEN 0 ELSE 1 END
                 WHERE resolved = 0;
                """,
                (lang, lang),
            )
        else:
            cur.execute(
                """
                UPDATE calls
                   SET dst_symbol = (
                     SELECT s.symbol_id FROM symbols s
                      WHERE s.name = calls.dst_name
                      ORDER BY s.symbol_id ASC LIMIT 1
                   ),
                       resolved = CASE WHEN (
                         SELECT s.symbol_id FROM symbols s
                          WHERE s.name = calls.dst_name
                          ORDER BY s.symbol_id ASC LIMIT 1
                       ) IS NULL THEN 0 ELSE 1 END
                 WHERE resolved = 0;
                """
            )

        # These edges are derived from `calls`. Ensure we don't duplicate them across runs.
        cur.execute("DELETE FROM edges WHERE kind IN ('CFG_IP_CALL','CFG_IP_RET','CALL');")

        # materialize interprocedural CFG edges
        cur.execute(
            """
            INSERT INTO edges(blob_hash, file_id, src, dst, kind, attrs)
            SELECT c.blob_hash, c.file_id, c.src_node, c.dst_symbol, 'CFG_IP_CALL', '{}'
              FROM calls c
             WHERE c.resolved = 1 AND c.dst_symbol IS NOT NULL;
            """
        )
        cur.execute(
            """
            INSERT INTO edges(blob_hash, file_id, src, dst, kind, attrs)
            SELECT c.blob_hash, c.file_id, c.dst_symbol, c.src_node, 'CFG_IP_RET', '{}'
              FROM calls c
             WHERE c.resolved = 1 AND c.dst_symbol IS NOT NULL;
            """
        )
        cur.execute(
            """
            INSERT INTO edges(blob_hash, file_id, src, dst, kind, attrs)
            SELECT c.blob_hash, c.file_id, c.src_node, c.dst_symbol, 'CALL', '{}'
              FROM calls c
             WHERE c.resolved = 1 AND c.dst_symbol IS NOT NULL;
            """
        )

    def count_symbols(self, blob_hash: str) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(1) FROM symbols WHERE blob_hash=?;", (blob_hash,))
        return int(cur.fetchone()[0])

    def count_calls(self, blob_hash: str) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(1) FROM calls WHERE blob_hash=?;", (blob_hash,))
        return int(cur.fetchone()[0])

    def symbols_for_blob(self, *, blob_hash: str, file_id: int, path: str) -> List[Symbol]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT symbol_id, lang, kind, name, start_line, start_col, end_line, end_col
              FROM symbols
             WHERE blob_hash=? AND file_id=?
             ORDER BY start_line ASC, start_col ASC;
            """,
            (blob_hash, int(file_id)),
        )
        out: List[Symbol] = []
        for sid, lang, kind, name, sl, sc, el, ec in cur.fetchall():
            out.append(
                Symbol(
                    id=sid,
                    name=name,
                    kind=kind,
                    span=(path, int(sl), int(sc), int(el), int(ec)),
                    lang=lang,
                    file=path,
                )
            )
        return out

    def repomap_files_for_rev(self, rev: str) -> List[Tuple[str, str, str, str, str, str]]:
        """Return RepoMap file rows for a specific revision.

        Returns tuples: (path, lang, blob_hash, generator, llm_model, file_summary_json).
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT f.path, f.lang, fv.blob_hash, rf.generator, rf.llm_model, rf.file_summary
              FROM file_versions fv
              JOIN files f ON f.file_id = fv.file_id
              JOIN repomap_files rf ON rf.file_id = fv.file_id AND rf.blob_hash = fv.blob_hash
             WHERE fv.rev = ?
             ORDER BY f.path ASC;
            """,
            (rev,),
        )
        return [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in cur.fetchall()]

    def repomap_run(self, rev: str) -> Optional[Dict[str, object]]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT created_at, duration_s, generator, llm_model,
                   llm_requests, prompt_tokens, completion_tokens, total_tokens, llm_time_s
              FROM repomap_runs
             WHERE rev=?
             ORDER BY created_at DESC
             LIMIT 1;
            """,
            (rev,),
        )
        row = cur.fetchone()
        if not row:
            return None
        (
            created_at,
            duration_s,
            generator,
            llm_model,
            llm_requests,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            llm_time_s,
        ) = row
        return {
            "created_at": float(created_at),
            "duration_s": float(duration_s),
            "generator": generator,
            "llm_model": llm_model,
            "llm_requests": int(llm_requests),
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "total_tokens": int(total_tokens),
            "llm_time_s": float(llm_time_s),
        }

    def stats(self) -> Dict[str, int]:
        cur = self.conn.cursor()
        out: Dict[str, int] = {}
        for table in ["files", "file_versions", "blobs", "nodes", "edges", "symbols", "calls"]:
            cur.execute(f"SELECT COUNT(1) FROM {table};")
            out[table] = int(cur.fetchone()[0])
        return out

    def has_repomap(self, blob_hash: str, file_id: int) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT 1 FROM repomap_files WHERE blob_hash=? AND file_id=? LIMIT 1;",
            (blob_hash, int(file_id)),
        )
        return cur.fetchone() is not None

    def repomap_file_meta(self, blob_hash: str, file_id: int) -> Optional[Dict[str, str]]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT generator, llm_model, hash FROM repomap_files WHERE blob_hash=? AND file_id=? LIMIT 1;",
            (blob_hash, int(file_id)),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"generator": row[0], "llm_model": row[1], "hash": row[2]}

    def put_repomap_file(
        self,
        *,
        blob_hash: str,
        file_id: int,
        path: str,
        lang: str,
        generator: str,
        llm_model: str,
        file_summary: str,
        hash_: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO repomap_files(blob_hash, file_id, path, lang, generator, llm_model, file_summary, hash)
            VALUES(?,?,?,?,?,?,?,?);
            """,
            (blob_hash, int(file_id), path, lang, generator, llm_model, file_summary, hash_),
        )

    def put_repomap_symbols(self, file_id: int, blob_hash: str, rows: Sequence[Tuple]) -> None:
        self.conn.executemany(
            """
            INSERT OR REPLACE INTO repomap_symbols(
              symbol_id, blob_hash, file_id, lang, kind, name,
              start_line, start_col, end_line, end_col,
              signature, summary_struct, summary_text, hash, generator, llm_model
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
            """,
            rows,
        )

    def put_repomap_packages(self, rev: str, packages: Sequence[Tuple[str, str, str, str, str]]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO repomap_packages(rev, package_path, summary, hash, generator, llm_model) VALUES(?,?,?,?,?,?);",
            [(rev, p, s, h, g, m) for (p, s, h, g, m) in packages],
        )

    def put_repomap_run(
        self,
        *,
        rev: str,
        duration_s: float,
        generator: str,
        llm_model: str,
        llm_requests: int,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        llm_time_s: float,
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO repomap_runs(
              rev, created_at, duration_s, generator, llm_model,
              llm_requests, prompt_tokens, completion_tokens, total_tokens, llm_time_s
            ) VALUES(?,?,?,?,?,?,?,?,?,?);
            """,
            (
                rev,
                time.time(),
                float(duration_s),
                generator,
                llm_model,
                int(llm_requests),
                int(prompt_tokens),
                int(completion_tokens),
                int(total_tokens),
                float(llm_time_s),
            ),
        )

    def resolve_symbol_ids(self, name: str, lang: Optional[str] = None, limit: int = 20) -> List[str]:
        cur = self.conn.cursor()
        if lang:
            cur.execute(
                "SELECT symbol_id FROM symbols WHERE name=? AND lang=? LIMIT ?;",
                (name, lang, int(limit)),
            )
        else:
            cur.execute("SELECT symbol_id FROM symbols WHERE name=? LIMIT ?;", (name, int(limit)))
        return [r[0] for r in cur.fetchall()]

    def neighbors(self, node_id: str, *, kind: Optional[str] = None, direction: str = "out", limit: int = 100) -> List[str]:
        cur = self.conn.cursor()
        if direction not in {"out", "in"}:
            raise ValueError("direction must be 'out' or 'in'")
        if direction == "out":
            if kind:
                cur.execute(
                    "SELECT dst FROM edges WHERE src=? AND kind=? LIMIT ?;",
                    (node_id, kind, int(limit)),
                )
            else:
                cur.execute("SELECT dst FROM edges WHERE src=? LIMIT ?;", (node_id, int(limit)))
        else:
            if kind:
                cur.execute(
                    "SELECT src FROM edges WHERE dst=? AND kind=? LIMIT ?;",
                    (node_id, kind, int(limit)),
                )
            else:
                cur.execute("SELECT src FROM edges WHERE dst=? LIMIT ?;", (node_id, int(limit)))
        return [r[0] for r in cur.fetchall()]

    def neighbors_multi(
        self,
        node_id: str,
        *,
        kinds: Sequence[str],
        direction: str = "out",
        limit: int = 200,
    ) -> List[str]:
        cur = self.conn.cursor()
        if direction not in {"out", "in"}:
            raise ValueError("direction must be 'out' or 'in'")
        if not kinds:
            return []
        placeholders = ",".join(["?"] * len(kinds))
        if direction == "out":
            cur.execute(
                f"SELECT dst FROM edges WHERE src=? AND kind IN ({placeholders}) LIMIT ?;",
                (node_id, *kinds, int(limit)),
            )
        else:
            cur.execute(
                f"SELECT src FROM edges WHERE dst=? AND kind IN ({placeholders}) LIMIT ?;",
                (node_id, *kinds, int(limit)),
            )
        return [r[0] for r in cur.fetchall()]

    def call_sites_by_names(
        self, names: Sequence[str], *, lang: Optional[str] = None, limit: int = 10_000
    ) -> List[str]:
        if not names:
            return []
        cur = self.conn.cursor()
        placeholders = ",".join(["?"] * len(names))
        if lang:
            cur.execute(
                f"""
                SELECT c.src_node
                  FROM calls c
                  JOIN files f ON f.file_id = c.file_id
                 WHERE f.lang = ? AND c.dst_name IN ({placeholders})
                 LIMIT ?;
                """,
                (lang, *names, int(limit)),
            )
        else:
            cur.execute(
                f"SELECT src_node FROM calls WHERE dst_name IN ({placeholders}) LIMIT ?;",
                (*names, int(limit)),
            )
        return [r[0] for r in cur.fetchall()]

    def search_code(self, query: str, *, lang: Optional[str] = None, limit: int = 20) -> List[Tuple[str, str]]:
        """Return [(path, snippet)] results; uses FTS if available."""
        cur = self.conn.cursor()
        try:
            if lang:
                cur.execute(
                    "SELECT path, snippet(fts_code, 2, '[', ']', '…', 10) FROM fts_code WHERE fts_code MATCH ? AND lang=? LIMIT ?;",
                    (query, lang, int(limit)),
                )
            else:
                cur.execute(
                    "SELECT path, snippet(fts_code, 2, '[', ']', '…', 10) FROM fts_code WHERE fts_code MATCH ? LIMIT ?;",
                    (query, int(limit)),
                )
            return [(r[0], r[1]) for r in cur.fetchall()]
        except sqlite3.OperationalError:
            # FTS unavailable, fallback to naive LIKE on paths.
            if lang:
                cur.execute(
                    "SELECT path, '' FROM files WHERE lang=? AND path LIKE ? LIMIT ?;",
                    (lang, f"%{query}%", int(limit)),
                )
            else:
                cur.execute(
                    "SELECT path, '' FROM files WHERE path LIKE ? LIMIT ?;",
                    (f"%{query}%", int(limit)),
                )
            return [(r[0], r[1]) for r in cur.fetchall()]

    def repomap_file(self, path: str) -> Optional[Dict[str, object]]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT generator, llm_model, file_summary FROM repomap_files WHERE path=? ORDER BY blob_hash DESC LIMIT 1;",
            (path,),
        )
        row = cur.fetchone()
        if not row:
            return None
        generator, llm_model, file_summary = row
        out = json.loads(file_summary)
        out["_meta"] = {"generator": generator, "llm_model": llm_model}
        return out

    def repomap_symbols_by_file(self, path: str, limit: int = 200) -> List[Dict[str, object]]:
        cur = self.conn.cursor()
        cur.execute("SELECT file_id FROM files WHERE path=? LIMIT 1;", (path,))
        row = cur.fetchone()
        if not row:
            return []
        file_id = int(row[0])
        cur.execute(
            """
            SELECT name, kind, signature, summary_text, summary_struct
              FROM repomap_symbols
             WHERE file_id=?
             ORDER BY start_line ASC, start_col ASC
             LIMIT ?;
            """,
            (file_id, int(limit)),
        )
        out = []
        for name, kind, sig, text, struct in cur.fetchall():
            out.append(
                {
                    "name": name,
                    "kind": kind,
                    "signature": sig,
                    "summary_text": text,
                    "summary_struct": json.loads(struct),
                }
            )
        return out


def _range_from_id(node_id: str) -> Tuple[int, int]:
    # id is "<prefix>:<start>-<end>"
    try:
        _, rest = node_id.split(":", 1)
        start_s, end_s = rest.split("-", 1)
        return int(start_s), int(end_s)
    except Exception:
        return (0, 0)


def index_repository(
    *,
    repo_root: Path,
    store: LiteCPGStore,
    builder,
    rev: str,
    base_rev: Optional[str] = None,
    config: RepoScanConfig = RepoScanConfig(),
    store_blobs: bool = False,
    logger=None,
) -> Dict[str, int]:
    """Index a repository into SQLite, skipping unchanged file blobs.

    Notes (CodeReview integration):
    - This vendored Lite-CPG build focuses on CPG primitives (nodes/edges/symbols/calls).
    - RepoMap/LLM summarization is intentionally not generated here to avoid
      introducing extra subsystems/dependencies into CodeReview.
    """
    with store.conn:
        store.begin_revision(rev, base_rev=base_rev)

        files_by_lang = scan_repo(repo_root, config=config)
        for lang, paths in files_by_lang.items():
            lang_n = normalize_lang(lang)
            parser = create_parser(lang_n)
            for path in paths:
                src = path.read_bytes()
                blob_hash = content_hash(src)
                stat = path.stat()

                file_id = store.upsert_file(str(path.resolve()), lang_n)
                store.upsert_file_version(rev, file_id, blob_hash, stat.st_size, stat.st_mtime)
                if store_blobs:
                    store.upsert_blob(blob_hash, src, compress=True)

                if store.has_blob_artifacts(blob_hash):
                    continue

                # Parse and build CPG for this file
                tree = parser.parse(src)
                pf = ParsedFile(path=path.resolve(), lang=lang_n, source=src, blob_hash=blob_hash)
                pf.root = tree.root_node  # type: ignore[attr-defined]

                cpg = builder.build([pf], interprocedural=False)
                try:
                    from ...core.dataflow import build_def_use

                    build_def_use(cpg, getattr(pf, "root"), id_prefix=pf.blob_hash)
                except Exception:
                    pass

                calls = []
                for ce in cpg.call_graph:
                    if ce.attrs.get("unresolved"):
                        calls.append((ce.src, ce.dst, None, 0, ce.attrs))
                    else:
                        sym = cpg.symbols.get(ce.dst)
                        calls.append((ce.src, sym.name if sym else "", ce.dst, 1, ce.attrs))

                store.put_file_artifacts(
                    file_id=file_id,
                    blob_hash=blob_hash,
                    lang=lang_n,
                    nodes=list(cpg.nodes.values()),
                    edges=cpg.edges,
                    symbols=list(cpg.symbols.values()),
                    calls=calls,
                    path=str(path.resolve()),
                    source_text=src.decode("utf-8", errors="ignore"),
                )

        store.resolve_calls()
    return store.stats()
