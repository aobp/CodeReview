"""Lite-CPG integration utilities for CodeReview.

This module manages per-diff SQLite databases and builds base/head revisions
into the DB by temporarily checking out git refs.

Constraints:
- Must NOT modify CodeReview/core or CodeReview/agents.
- Must be safe to call from main.py before workflow execution.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional

from util.git_utils import ensure_head_version, get_repo_name

from lite_cpg.core.builder import LiteCPGBuilder
from lite_cpg.repo.scan import RepoScanConfig
from lite_cpg.store.backends.sqlite import LiteCPGStore, index_repository


def _git_rev_parse(repo_path: Path, ref: str) -> Optional[str]:
    try:
        r = subprocess.run(
            ["git", "rev-parse", ref],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        return r.stdout.strip()
    except Exception:
        return None


def _pick_seed_db(dir_path: Path, *, base_sha: Optional[str], head_sha: Optional[str]) -> Optional[Path]:
    """Pick a DB to copy from to maximize artifact reuse."""
    if not dir_path.exists():
        return None
    dbs = sorted(dir_path.glob("*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not dbs:
        return None

    if base_sha and head_sha:
        base12, head12 = base_sha[:12], head_sha[:12]
        for p in dbs:
            name = p.name
            if name.startswith(f"{base12}_{head12}_"):
                return p
    return dbs[0]


def _db_get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    cur = conn.cursor()
    cur.execute("SELECT value FROM meta WHERE key=? LIMIT 1;", (key,))
    row = cur.fetchone()
    return str(row[0]) if row else None


def _db_set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?);", (key, value))


def _db_revision_exists(conn: sqlite3.Connection, rev: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM revisions WHERE rev=? LIMIT 1;", (rev,))
    return cur.fetchone() is not None


def _db_is_ready(
    *,
    db_path: Path,
    base_sha: Optional[str],
    head_sha: Optional[str],
    diff_sha12: str,
) -> bool:
    """Fast check: if DB already matches current base/head/diff and has artifacts, skip rebuilding."""
    try:
        conn = sqlite3.connect(str(db_path))
    except Exception:
        return False

    try:
        # Basic sanity: must have both revisions recorded.
        if not (_db_revision_exists(conn, "base") and _db_revision_exists(conn, "head")):
            return False

        # Must have at least some artifacts; otherwise treat as incomplete build.
        cur = conn.cursor()
        cur.execute("SELECT COUNT(1) FROM nodes;")
        nodes_n = int(cur.fetchone()[0])
        if nodes_n <= 0:
            return False

        cur.execute("SELECT COUNT(1) FROM file_versions WHERE rev='base';")
        base_files_n = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(1) FROM file_versions WHERE rev='head';")
        head_files_n = int(cur.fetchone()[0])
        if base_files_n <= 0 or head_files_n <= 0:
            return False

        # Strong match when meta exists (prevents branch-name ref drift).
        meta_diff = _db_get_meta(conn, "diff_sha12")
        if meta_diff and meta_diff != diff_sha12:
            return False

        meta_base = _db_get_meta(conn, "base_sha")
        meta_head = _db_get_meta(conn, "head_sha")
        # If meta is present, require exact match.
        if meta_base and base_sha and meta_base != base_sha:
            return False
        if meta_head and head_sha and meta_head != head_sha:
            return False

        return True
    finally:
        try:
            conn.close()
        except Exception:
            pass


def prepare_lite_cpg_db(
    *,
    codereview_root: Path,
    repo_path: Path,
    base_ref: str,
    head_ref: str,
    pr_diff: str,
    store_blobs: bool = True,
) -> Path:
    """Create or reuse a per-diff Lite-CPG sqlite DB and ensure base/head are indexed."""
    codereview_root = Path(codereview_root).resolve()
    repo_path = Path(repo_path).resolve()

    repo_name = get_repo_name(repo_path)
    base_sha = _git_rev_parse(repo_path, base_ref)
    head_sha = _git_rev_parse(repo_path, head_ref)
    diff_sha12 = hashlib.sha256((pr_diff or "").encode("utf-8")).hexdigest()[:12]

    base12 = (base_sha[:12] if base_sha else base_ref.replace("/", "_")[:12])
    head12 = (head_sha[:12] if head_sha else head_ref.replace("/", "_")[:12])

    db_dir = codereview_root / ".storage" / "lite_cpg" / repo_name
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / f"{base12}_{head12}_{diff_sha12}.sqlite"

    if not db_path.exists():
        seed = _pick_seed_db(db_dir, base_sha=base_sha, head_sha=head_sha)
        if seed:
            shutil.copy2(seed, db_path)
        else:
            # Create an empty DB with schema.
            LiteCPGStore(db_path).close()

    # Export to env early so downstream tools can at least locate the DB,
    # even if indexing fails part-way.
    os.environ["LITE_CPG_DB_PATH"] = str(db_path)
    os.environ.setdefault("LITE_CPG_DEFAULT_REV", "head")
    os.environ.pop("LITE_CPG_INDEX_ERROR", None)
    os.environ.pop("LITE_CPG_INDEX_SKIPPED", None)

    # If this per-diff DB is already fully indexed for the same base/head/diff, skip rebuild.
    if db_path.exists() and _db_is_ready(db_path=db_path, base_sha=base_sha, head_sha=head_sha, diff_sha12=diff_sha12):
        os.environ["LITE_CPG_INDEX_SKIPPED"] = "1"
        return db_path

    # Build base/head revisions into this DB.
    store = LiteCPGStore(db_path)
    builder = LiteCPGBuilder()
    scan_cfg = RepoScanConfig()
    try:
        ensure_head_version(repo_path, base_ref)
        index_repository(repo_root=repo_path, store=store, builder=builder, rev="base", config=scan_cfg, store_blobs=store_blobs)

        ensure_head_version(repo_path, head_ref)
        index_repository(
            repo_root=repo_path,
            store=store,
            builder=builder,
            rev="head",
            base_rev="base",
            config=scan_cfg,
            store_blobs=store_blobs,
        )
    finally:
        store.close()
        # Ensure we end on head for the rest of CodeReview flow.
        try:
            ensure_head_version(repo_path, head_ref)
        except Exception:
            pass

    # Record mapping so subsequent runs can skip checkout/index when base/head/diff are unchanged.
    try:
        conn = sqlite3.connect(str(db_path))
        with conn:
            _db_set_meta(conn, "diff_sha12", diff_sha12)
            if base_sha:
                _db_set_meta(conn, "base_sha", base_sha)
            if head_sha:
                _db_set_meta(conn, "head_sha", head_sha)
        conn.close()
    except Exception:
        pass

    return db_path


