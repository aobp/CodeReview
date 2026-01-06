from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from github_pat.lock import file_lock


def _run_git(args: list[str], *, cwd: Path) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (cwd={cwd}): {result.stderr.strip() or result.stdout.strip()}"
        )


@dataclass(frozen=True)
class RepoCachePaths:
    mirror_dir: Path
    lock_path: Path


class RepoCache:
    def __init__(self, *, mirror_root: Path, work_root: Path, lock_root: Path) -> None:
        # Resolve to absolute paths to avoid accidentally creating nested `.storage/...`
        # directories when `git clone` is executed with a different `cwd`.
        self._mirror_root = Path(mirror_root).resolve()
        self._work_root = Path(work_root).resolve()
        self._lock_root = Path(lock_root).resolve()

    def paths_for(self, owner: str, repo: str) -> RepoCachePaths:
        mirror_dir = self._mirror_root / owner / f"{repo}.git"
        lock_path = self._lock_root / f"{owner}_{repo}.lock"
        return RepoCachePaths(mirror_dir=mirror_dir, lock_path=lock_path)

    def ensure_mirror(self, *, owner: str, repo: str, clone_url: str) -> RepoCachePaths:
        paths = self.paths_for(owner, repo)
        paths.mirror_dir.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(paths.lock_path):
            if not paths.mirror_dir.exists():
                result = subprocess.run(
                    ["git", "clone", "--mirror", clone_url, str(paths.mirror_dir)],
                    cwd=paths.mirror_dir.parent,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"git clone --mirror failed: {result.stderr.strip() or result.stdout.strip()}"
                    )
        return paths

    def fetch_pr_and_base(
        self,
        *,
        mirror_dir: Path,
        lock_path: Path,
        pr_number: int,
        base_ref: str,
    ) -> tuple[str, str]:
        pr_branch = f"pr-{pr_number}"
        base_branch = f"base-{base_ref}"
        with file_lock(lock_path):
            _run_git(["fetch", "--prune", "origin"], cwd=mirror_dir)
            _run_git(["fetch", "origin", f"pull/{pr_number}/head:refs/heads/{pr_branch}"], cwd=mirror_dir)
            _run_git(["fetch", "origin", f"{base_ref}:refs/heads/{base_branch}"], cwd=mirror_dir)
        return pr_branch, base_branch

    def add_worktree(
        self,
        *,
        mirror_dir: Path,
        lock_path: Path,
        owner: str,
        repo: str,
        pr_number: int,
        head_sha: str,
        checkout_branch: str,
    ) -> Path:
        work_dir = self._work_root / owner / repo / str(pr_number) / head_sha
        work_dir.parent.mkdir(parents=True, exist_ok=True)
        if work_dir.exists():
            self.remove_worktree(mirror_dir=mirror_dir, lock_path=lock_path, work_dir=work_dir)
            if work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)
        with file_lock(lock_path):
            _run_git(["worktree", "add", "--force", str(work_dir), checkout_branch], cwd=mirror_dir)
        return work_dir

    def remove_worktree(self, *, mirror_dir: Path, lock_path: Path, work_dir: Path) -> None:
        with file_lock(lock_path):
            result = subprocess.run(
                ["git", "worktree", "remove", "--force", str(work_dir)],
                cwd=mirror_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if result.returncode != 0 and work_dir.exists():
                raise RuntimeError(
                    f"git worktree remove failed: {result.stderr.strip() or result.stdout.strip()}"
                )
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=mirror_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
