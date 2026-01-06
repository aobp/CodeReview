from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Job:
    id: int
    repo_full_name: str
    pr_number: int
    pr_url: str
    comment_id: int
    sender: str
    status: str
    created_at: int
    updated_at: int
    head_sha: Optional[str] = None
    base_ref: Optional[str] = None
    error: Optional[str] = None


class JobStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  repo_full_name TEXT NOT NULL,
                  pr_number INTEGER NOT NULL,
                  pr_url TEXT NOT NULL,
                  comment_id INTEGER NOT NULL,
                  sender TEXT NOT NULL,
                  status TEXT NOT NULL,
                  head_sha TEXT,
                  base_ref TEXT,
                  error TEXT,
                  created_at INTEGER NOT NULL,
                  updated_at INTEGER NOT NULL,
                  UNIQUE(repo_full_name, comment_id)
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_repo_pr ON jobs(repo_full_name, pr_number);")

    def enqueue_job(
        self,
        *,
        repo_full_name: str,
        pr_number: int,
        pr_url: str,
        comment_id: int,
        sender: str,
        cooldown_seconds: int,
    ) -> Optional[int]:
        now = int(time.time())
        with self._connect() as conn:
            if cooldown_seconds > 0:
                row = conn.execute(
                    """
                    SELECT status, updated_at
                    FROM jobs
                    WHERE repo_full_name = ? AND pr_number = ?
                    ORDER BY id DESC
                    LIMIT 1;
                    """,
                    (repo_full_name, pr_number),
                ).fetchone()
                if row and row["status"] in {"queued", "running"}:
                    return None
                if row and (now - int(row["updated_at"])) < cooldown_seconds:
                    return None

            try:
                cur = conn.execute(
                    """
                    INSERT INTO jobs (
                      repo_full_name, pr_number, pr_url, comment_id, sender,
                      status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?);
                    """,
                    (repo_full_name, pr_number, pr_url, comment_id, sender, now, now),
                )
                return int(cur.lastrowid)
            except sqlite3.IntegrityError:
                return None

    def get_job(self, job_id: int) -> Optional[Job]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?;", (job_id,)).fetchone()
            if not row:
                return None
            return Job(**dict(row))

    def list_unfinished_jobs(self) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM jobs WHERE status IN ('queued', 'running') ORDER BY id ASC;"
            ).fetchall()
            return [int(r["id"]) for r in rows]

    def mark_running(self, job_id: int) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='running', updated_at=? WHERE id=?;",
                (now, job_id),
            )

    def mark_meta(self, job_id: int, *, head_sha: str, base_ref: str) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET head_sha=?, base_ref=?, updated_at=? WHERE id=?;",
                (head_sha, base_ref, now, job_id),
            )

    def mark_done(self, job_id: int) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='done', error=NULL, updated_at=? WHERE id=?;",
                (now, job_id),
            )

    def mark_failed(self, job_id: int, error: str) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', error=?, updated_at=? WHERE id=?;",
                (error[:2000], now, job_id),
            )
