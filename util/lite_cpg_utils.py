"""Lite-CPG integration utilities for CodeReview.

This module manages per-diff SQLite databases and builds base/head revisions
into the DB by temporarily checking out git refs.

Constraints:
- Must NOT modify CodeReview/core or CodeReview/agents.
- Must be safe to call from main.py before workflow execution.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from util.git_utils import ensure_head_version, extract_files_from_diff, get_repo_name

from lite_cpg.core.builder import LiteCPGBuilder
from lite_cpg.repo.scan import RepoScanConfig, infer_language
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


def _db_meta_from_path(db_path: Path, key: str) -> Optional[str]:
    try:
        conn = sqlite3.connect(str(db_path))
    except Exception:
        return None
    try:
        return _db_get_meta(conn, key)
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _pick_seed_db(
    dir_path: Path,
    *,
    base_sha: Optional[str],
    head_sha: Optional[str],
    scope: Optional[str] = None,
) -> Optional[Path]:
    """Pick a DB to copy from to maximize artifact reuse."""
    if not dir_path.exists():
        return None
    dbs = sorted(dir_path.glob("*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not dbs:
        return None

    if scope:
        scoped = []
        for p in dbs:
            meta_scope = _db_meta_from_path(p, "cpg_scope")
            if meta_scope == scope:
                scoped.append(p)
        dbs = scoped
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
    scope: Optional[str] = None,
    dep_depth: Optional[int] = None,
    dep_max_files: Optional[int] = None,
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

        if scope:
            meta_scope = _db_get_meta(conn, "cpg_scope")
            if meta_scope and meta_scope != scope:
                return False
        if dep_depth is not None:
            meta_depth = _db_get_meta(conn, "cpg_dep_depth")
            try:
                if meta_depth and int(meta_depth) != int(dep_depth):
                    return False
            except Exception:
                return False
        if dep_max_files is not None:
            meta_max = _db_get_meta(conn, "cpg_dep_max_files")
            try:
                if meta_max and int(meta_max) != int(dep_max_files):
                    return False
            except Exception:
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

    # PR-scoped dependency closure controls (env-driven)
    # - LITE_CPG_DEP_DEPTH: max dependency expansion hops from PR-changed files (default 5)
    # - LITE_CPG_DEP_MAX_FILES: hard cap on total files indexed per revision (default 2000)
    scope = "pr"
    try:
        dep_depth = int(os.environ.get("LITE_CPG_DEP_DEPTH", "5"))
    except Exception:
        dep_depth = 5
    try:
        dep_max_files = int(os.environ.get("LITE_CPG_DEP_MAX_FILES", "2000"))
    except Exception:
        dep_max_files = 2000
    dep_depth = max(0, dep_depth)
    dep_max_files = max(1, dep_max_files)

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
        # Avoid inheriting a huge legacy (repo-wide) DB: only seed from same scope.
        seed = _pick_seed_db(db_dir, base_sha=base_sha, head_sha=head_sha, scope=scope)
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
    if db_path.exists() and _db_is_ready(
        db_path=db_path,
        base_sha=base_sha,
        head_sha=head_sha,
        diff_sha12=diff_sha12,
        scope=scope,
        dep_depth=dep_depth,
        dep_max_files=dep_max_files,
    ):
        os.environ["LITE_CPG_INDEX_SKIPPED"] = "1"
        return db_path

    def _seed_paths_from_diff() -> List[Path]:
        rels = extract_files_from_diff(pr_diff or "")
        out: List[Path] = []
        for r in rels:
            try:
                p = (repo_path / r).resolve()
            except Exception:
                continue
            # Only index languages supported by lite_cpg scanner
            if infer_language(p) is None:
                continue
            out.append(p)
        # de-dup
        seen: Set[str] = set()
        uniq: List[Path] = []
        for p in out:
            sp = str(p)
            if sp in seen:
                continue
            seen.add(sp)
            uniq.append(p)
        return uniq

    _TS_SPEC_RE = re.compile(r"(?:from\s+|import\s+)(['\"])([^'\"]+)\1")
    _TS_REQUIRE_RE = re.compile(r"require\(\s*(['\"])([^'\"]+)\1\s*\)")

    def _python_deps(path: Path, *, repo_root: Path) -> List[Path]:
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
        try:
            mod = ast.parse(src)
        except Exception:
            return []

        deps: List[Path] = []

        def module_candidates(module: str, *, importer: Path) -> List[Path]:
            m = (module or "").strip()
            if not m:
                return []
            # Relative module ".x" / "..x": resolve against importer directory (support multi-dot)
            if m.startswith("."):
                dots = len(m) - len(m.lstrip("."))
                rel = m.lstrip(".").replace(".", "/")
                base_dir = importer.resolve().parent
                for _ in range(max(0, dots - 1)):
                    base_dir = base_dir.parent
                if not rel:
                    return [base_dir / "__init__.py"]
                return [base_dir / f"{rel}.py", base_dir / rel / "__init__.py"]
            # Absolute module "a.b"
            rel = m.replace(".", "/")
            root = repo_root.resolve()
            return [root / f"{rel}.py", root / rel / "__init__.py"]

        for node in mod.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    deps.extend(module_candidates(alias.name, importer=path))
            elif isinstance(node, ast.ImportFrom):
                level = int(getattr(node, "level", 0) or 0)
                module = getattr(node, "module", None) or ""
                from_mod = ("." * level + module) if level else module
                if from_mod:
                    deps.extend(module_candidates(from_mod, importer=path))
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    # Best-effort: from pkg import submodule -> pkg/submodule.py
                    if from_mod:
                        deps.extend(module_candidates(f"{from_mod}.{alias.name}", importer=path))
                    elif level:
                        deps.extend(module_candidates("." * level + alias.name, importer=path))
        # filter existing + supported
        out: List[Path] = []
        for p in deps:
            try:
                rp = p.resolve()
            except Exception:
                continue
            if rp.is_file() and infer_language(rp) is not None:
                out.append(rp)
        return out

    def _ts_deps(path: Path) -> List[Path]:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return []
        specs: List[str] = []
        for m in _TS_SPEC_RE.finditer(text):
            specs.append(m.group(2))
        for m in _TS_REQUIRE_RE.finditer(text):
            specs.append(m.group(2))
        base_dir = path.resolve().parent
        cands: List[Path] = []
        for spec in specs:
            s = (spec or "").strip()
            if not s.startswith("."):
                continue
            base = (base_dir / s).resolve()
            cands.extend(
                [
                    Path(f"{base}.ts"),
                    Path(f"{base}.tsx"),
                    Path(f"{base}.js"),
                    base / "index.ts",
                    base / "index.tsx",
                    base / "index.js",
                ]
            )
        out: List[Path] = []
        for p in cands:
            try:
                rp = p.resolve()
            except Exception:
                continue
            if rp.is_file() and infer_language(rp) is not None:
                out.append(rp)
        return out

    def _deps_for_file(path: Path, *, repo_root: Path) -> List[Path]:
        lang = infer_language(path)
        if lang == "python":
            return _python_deps(path, repo_root=repo_root)
        if lang == "typescript":
            return _ts_deps(path)
        # Other languages need dedicated module resolvers; keep minimal.
        return []

    def _closure(seed: Sequence[Path], *, repo_root: Path, scan_cfg: RepoScanConfig) -> List[Path]:
        seen: Set[str] = set()
        frontier: List[Tuple[Path, int]] = [(p, 0) for p in seed]
        out: List[Path] = []
        while frontier and len(seen) < dep_max_files:
            path, depth = frontier.pop(0)
            try:
                rp = Path(path).resolve()
            except Exception:
                continue
            sp = str(rp)
            if sp in seen:
                continue
            # Exclude large dirs and oversized files similarly to scan_repo
            if any(part in scan_cfg.exclude_dirs for part in rp.parts):
                continue
            if not rp.is_file():
                continue
            try:
                if rp.stat().st_size > scan_cfg.max_file_bytes:
                    continue
            except OSError:
                continue
            if infer_language(rp) is None:
                continue
            seen.add(sp)
            out.append(rp)
            if depth >= dep_depth:
                continue
            for dep in _deps_for_file(rp, repo_root=repo_root):
                if len(seen) >= dep_max_files:
                    break
                frontier.append((dep, depth + 1))
        # stable order
        return sorted(out, key=lambda p: str(p))

    seed_paths = _seed_paths_from_diff()

    # Build base/head revisions into this DB.
    store = LiteCPGStore(db_path)
    builder = LiteCPGBuilder()
    scan_cfg = RepoScanConfig()
    try:
        ensure_head_version(repo_path, base_ref)
        base_paths = _closure(seed_paths, repo_root=repo_path, scan_cfg=scan_cfg)
        index_repository(
            repo_root=repo_path,
            store=store,
            builder=builder,
            rev="base",
            config=scan_cfg,
            store_blobs=store_blobs,
            paths=base_paths,
        )

        ensure_head_version(repo_path, head_ref)
        head_paths = _closure(seed_paths, repo_root=repo_path, scan_cfg=scan_cfg)
        index_repository(
            repo_root=repo_path,
            store=store,
            builder=builder,
            rev="head",
            base_rev="base",
            config=scan_cfg,
            store_blobs=store_blobs,
            paths=head_paths,
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
            _db_set_meta(conn, "cpg_scope", scope)
            _db_set_meta(conn, "cpg_dep_depth", str(dep_depth))
            _db_set_meta(conn, "cpg_dep_max_files", str(dep_max_files))
            if base_sha:
                _db_set_meta(conn, "base_sha", base_sha)
            if head_sha:
                _db_set_meta(conn, "head_sha", head_sha)
        conn.close()
    except Exception:
        pass

    return db_path


