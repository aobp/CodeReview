"""
Quick manual test for Lite-CPG.

Usage:
  python -m code.lite_cpg.run_demo --lang python --files path/to/file.py
  python -m code.lite_cpg.run_demo --lang typescript --glob "src/**/*.ts"
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Iterable, List

from ..core import (
    LiteCPGBuilder,
    build_def_use,
)
from ..analysis import (
    backward_slice,
    forward_slice,
)
from ..store.backends.sqlite import LiteCPGStore, default_store_paths, index_repository
from ..llm.openai_compat import OpenAICompatConfig
from ..llm.repomap_llm import RepoMapLLMConfig
from ..config.repomap_policy import RepoMapPolicy, load_policy


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Lite-CPG demo runner")
    ap.add_argument("--lang", help="Language: typescript/python/go/java/ruby (required for --files/--glob)")
    ap.add_argument("--files", nargs="*", help="Explicit file paths")
    ap.add_argument("--glob", help="Glob pattern (relative to cwd), e.g., 'src/**/*.ts'")
    ap.add_argument("--repo", help="Repository root to scan/build (overrides --files/--glob)")
    ap.add_argument("--out", help="Persist into SQLite store directory (default: <repo>/.lite_cpg)")
    ap.add_argument("--rev", default="workdir", help="Revision id for persistence (e.g., commit SHA)")
    ap.add_argument("--store-blobs", action="store_true", help="Store compressed file contents in DB")
    ap.add_argument("--repomap-llm", action="store_true", help="Use LLM to generate RepoMap summaries")
    ap.add_argument("--llm-base-url", default="", help="OpenAI-compatible base URL (e.g., https://api.deepseek.com/v1)")
    ap.add_argument("--llm-model", default="", help="Model name (e.g., deepseek-chat)")
    ap.add_argument("--llm-key-env", default="DEEPSEEK_API_KEY", help="Env var name for API key")
    ap.add_argument("--llm-concurrency", type=int, default=4, help="Max concurrent LLM requests per file")
    ap.add_argument("--repomap-force", action="store_true", help="Force regenerate RepoMap summaries")
    ap.add_argument("--repomap-policy", default="", help="RepoMap policy JSON path (enables triage/coverage control)")
    ap.add_argument("--repomap-top-percent", type=float, default=0.0, help="Override policy deep_top_percent (0=use policy)")
    ap.add_argument("--repomap-max-dirs", type=int, default=0, help="Override policy max_dirs (0=use policy)")
    ap.add_argument("--log-file", default="", help="Write logs to this file (default: <store>/run.log when persisting)")
    ap.add_argument("--verbose", action="store_true", help="Verbose logging")
    ap.add_argument("--show", action="store_true", help="Print a small RepoMap sample after persistence")
    ap.add_argument("--max-slice", type=int, default=20, help="Max nodes in slice output")
    return ap.parse_args()


def gather_files(args: argparse.Namespace) -> List[Path]:
    files: List[Path] = []
    if args.files:
        files.extend(Path(f).resolve() for f in args.files)
    if args.glob:
        files.extend(Path(".").glob(args.glob))
    return files


def _configure_logging(*, verbose: bool, log_file: str = "") -> logging.Logger:
    logger = logging.getLogger("lite_cpg")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


def _show_repomap_sample(store: LiteCPGStore, *, logger: logging.Logger) -> None:
    cur = store.conn.cursor()
    cur.execute("SELECT path FROM repomap_files ORDER BY path LIMIT 3;")
    paths = [r[0] for r in cur.fetchall()]
    for p in paths:
        fs = store.repomap_file(p)
        syms = store.repomap_symbols_by_file(p, limit=5)
        logger.info("RepoMap file=%s summary=%s", p, fs)
        logger.info("RepoMap symbols(file=%s)=%s", p, [s.get("summary_text") for s in syms])


def main() -> None:
    args = parse_args()
    builder = LiteCPGBuilder()
    if args.repo:
        repo_root = Path(args.repo)
        # UX: if user asks for RepoMap/persistence features but forgot --out, persist to default store.
        if args.out is None and (
            args.repomap_llm
            or args.repomap_policy
            or args.repomap_force
            or args.store_blobs
            or args.show
            or bool(args.log_file)
        ):
            args.out = ""
        if args.out is not None:
            out_root = Path(args.out) if args.out else default_store_paths(repo_root).root
            log_file = args.log_file or str(out_root / "run.log")
            logger = _configure_logging(verbose=args.verbose, log_file=log_file)
            logger.info("Indexing repo=%s rev=%s out=%s", str(repo_root), args.rev, str(out_root))
            store = LiteCPGStore(out_root / "cpg.sqlite")
            try:
                repomap_llm = None
                if args.repomap_llm:
                    base = args.llm_base_url or "https://api.deepseek.com/v1"
                    model = args.llm_model or "deepseek-chat"
                    repomap_llm = RepoMapLLMConfig(
                        api=OpenAICompatConfig(
                            base_url=base,
                            api_key_env=args.llm_key_env,
                            model=model,
                        ),
                        concurrency=max(1, int(args.llm_concurrency)),
                    )
                repomap_policy = None
                if args.repomap_policy or args.repomap_top_percent or args.repomap_max_dirs:
                    repomap_policy = load_policy(Path(args.repomap_policy).resolve() if args.repomap_policy else None)
                    if args.repomap_top_percent:
                        repomap_policy = RepoMapPolicy(
                            **{**repomap_policy.__dict__, "deep_top_percent": float(args.repomap_top_percent)}
                        )
                    if args.repomap_max_dirs:
                        repomap_policy = RepoMapPolicy(**{**repomap_policy.__dict__, "max_dirs": int(args.repomap_max_dirs)})
                    repomap_policy.validate()
                stats = index_repository(
                    repo_root=repo_root,
                    store=store,
                    builder=builder,
                    rev=args.rev,
                    store_blobs=args.store_blobs,
                    repomap_llm=repomap_llm,
                    repomap_force=args.repomap_force,
                    repomap_policy=repomap_policy,
                    logger=logger,
                )
                logger.info("Persisted store: %s", str(store.db_path))
                logger.info("DB stats: %s", stats)
                run_meta = store.repomap_run(args.rev)
                if run_meta:
                    logger.info("RepoMap run: %s", run_meta)
                if args.show:
                    _show_repomap_sample(store, logger=logger)
            finally:
                store.close()
            return

        parsed = builder.parse_repo(repo_root)
        cpg = builder.build(parsed, interprocedural=True)
    else:
        _configure_logging(verbose=args.verbose)
        if not args.lang:
            raise SystemExit("--lang is required when using --files/--glob")
        files = gather_files(args)
        if not files:
            raise SystemExit("No input files provided.")
        parsed = builder.parse_files(files, lang=args.lang)
        cpg = builder.build(parsed, interprocedural=False)

    # Build def-use for each parsed file
    for pf in parsed:
        build_def_use(cpg, getattr(pf, "root"), id_prefix=pf.blob_hash)

    print(f"Built CPG for {len(parsed)} files")
    print(f"nodes={len(cpg.nodes)}, edges={len(cpg.edges)}, calls={len(cpg.call_graph)}, symbols={len(cpg.symbols)}")

    # Show sample slices
    if cpg.nodes:
        first_id = next(iter(cpg.nodes))
        bw = backward_slice(cpg, [first_id], max_nodes=args.max_slice)
        fw = forward_slice(cpg, [first_id], max_nodes=args.max_slice)
        print("backward slice sample:", bw)
        print("forward slice sample:", fw)


if __name__ == "__main__":
    main()
