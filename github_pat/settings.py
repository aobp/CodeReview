from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: str) -> int:
    try:
        return int(os.environ.get(name, default).strip())
    except Exception:
        return int(default)


def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    github_token: str
    github_webhook_secret: str
    github_api_base_url: str

    allowed_repos: set[str]
    bot_trigger: str
    allow_unsigned_webhooks: bool

    db_path: Path
    mirror_root: Path
    work_root: Path
    lock_root: Path

    max_concurrent_jobs: int
    cooldown_seconds: int
    max_review_comments: int
    max_line_fuzz: int
    keep_worktree: bool

    enable_repomap: bool
    enable_lite_cpg: bool
    enable_lint: bool

    @staticmethod
    def load() -> "Settings":
        allowed_repos_raw = _env_str("ALLOWED_REPOS", "").strip()
        allowed_repos = {r.strip() for r in allowed_repos_raw.split(",") if r.strip()}

        return Settings(
            github_token=_env_str("GITHUB_TOKEN", "").strip(),
            github_webhook_secret=_env_str("GITHUB_WEBHOOK_SECRET", "").strip(),
            github_api_base_url=_env_str("GITHUB_API_BASE_URL", "https://api.github.com").strip().rstrip("/"),
            allowed_repos=allowed_repos,
            bot_trigger=_env_str("BOT_TRIGGER", "@cptbot review").strip(),
            allow_unsigned_webhooks=_env_bool("ALLOW_UNSIGNED_WEBHOOKS", "0"),
            db_path=Path(_env_str("DB_PATH", ".storage/github_pat/jobs.sqlite3")),
            mirror_root=Path(_env_str("MIRROR_ROOT", ".storage/github_pat/mirrors")),
            work_root=Path(_env_str("WORK_ROOT", ".storage/github_pat/work")),
            lock_root=Path(_env_str("LOCK_ROOT", ".storage/github_pat/locks")),
            max_concurrent_jobs=max(1, _env_int("MAX_CONCURRENT_JOBS", "2")),
            cooldown_seconds=max(0, _env_int("COOLDOWN_SECONDS", "60")),
            max_review_comments=max(1, _env_int("MAX_REVIEW_COMMENTS", "50")),
            max_line_fuzz=max(0, _env_int("MAX_LINE_FUZZ", "3")),
            keep_worktree=_env_bool("KEEP_WORKTREE", "0"),
            enable_repomap=_env_bool("ENABLE_REPOMAP", "1"),
            enable_lite_cpg=_env_bool("ENABLE_LITE_CPG", "1"),
            enable_lint=_env_bool("ENABLE_LINT", "1"),
        )
