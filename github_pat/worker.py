from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from github_pat.comment_builder import build_review_comments
from github_pat.db import JobStore
from github_pat.github_api import GitHubClient
from github_pat.git_cache import RepoCache
from github_pat.review_runner import run_review_for_pr
from github_pat.settings import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerDeps:
    settings: Settings
    store: JobStore
    github: GitHubClient
    repo_cache: RepoCache


class JobWorker:
    def __init__(self, deps: WorkerDeps, queue: "asyncio.Queue[int]") -> None:
        self._deps = deps
        self._queue = queue
        self._stop = asyncio.Event()
        self._sema = asyncio.Semaphore(deps.settings.max_concurrent_jobs)
        self._tasks: set[asyncio.Task[None]] = set()

    def _track_task(self, task: asyncio.Task[None]) -> None:
        self._tasks.add(task)

        def _done(_: asyncio.Task[None]) -> None:
            self._tasks.discard(task)

        task.add_done_callback(_done)

    async def start(self) -> None:
        for job_id in self._deps.store.list_unfinished_jobs():
            await self._queue.put(job_id)
        self._track_task(asyncio.create_task(self._run_loop()))

    async def stop(self) -> None:
        self._stop.set()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            job_id = await self._queue.get()
            self._track_task(asyncio.create_task(self._process_with_sema(job_id)))

    async def _process_with_sema(self, job_id: int) -> None:
        await self._sema.acquire()
        try:
            await self._process_job(job_id)
        finally:
            self._sema.release()
            self._queue.task_done()

    async def _process_job(self, job_id: int) -> None:
        settings = self._deps.settings
        job = self._deps.store.get_job(job_id)
        if not job:
            return

        self._deps.store.mark_running(job_id)

        try:
            pr = await self._deps.github.get_pr(job.pr_url)
            logger.info("job=%s start repo=%s pr=%s", job_id, pr.full_name, pr.number)
            if settings.allowed_repos and pr.full_name not in settings.allowed_repos:
                raise RuntimeError(f"repo not allowed: {pr.full_name}")

            self._deps.store.mark_meta(job_id, head_sha=pr.head_sha, base_ref=pr.base_ref)

            clone_url = f"https://github.com/{pr.full_name}.git"
            cache_paths = self._deps.repo_cache.ensure_mirror(owner=pr.owner, repo=pr.repo, clone_url=clone_url)
            pr_branch, base_branch = self._deps.repo_cache.fetch_pr_and_base(
                mirror_dir=cache_paths.mirror_dir,
                lock_path=cache_paths.lock_path,
                pr_number=pr.number,
                base_ref=pr.base_ref,
            )

            work_dir = self._deps.repo_cache.add_worktree(
                mirror_dir=cache_paths.mirror_dir,
                lock_path=cache_paths.lock_path,
                owner=pr.owner,
                repo=pr.repo,
                pr_number=pr.number,
                head_sha=pr.head_sha,
                checkout_branch=pr_branch,
            )

            try:
                results = await run_review_for_pr(
                    repo_path=work_dir,
                    base_branch=base_branch,
                    head_branch=pr_branch,
                    enable_repomap=settings.enable_repomap,
                    enable_lite_cpg=settings.enable_lite_cpg,
                    enable_lint=settings.enable_lint,
                )

                pr_diff = str(results.get("__pr_diff", ""))
                confirmed_issues = results.get("confirmed_issues", []) or []
                built = build_review_comments(
                    pr_diff=pr_diff,
                    confirmed_issues=confirmed_issues,
                    max_review_comments=settings.max_review_comments,
                    max_line_fuzz=settings.max_line_fuzz,
                )

                summary = f"Triggered by `{settings.bot_trigger}`. Total issues: {built.total_issues}."
                if built.skipped:
                    summary += f" Skipped inline: {len(built.skipped)}."

                review_failed: str | None = None
                if built.review_comments:
                    try:
                        await self._deps.github.create_review(
                            owner=pr.owner,
                            repo=pr.repo,
                            pr_number=pr.number,
                            commit_id=pr.head_sha,
                            body=summary,
                            comments=built.review_comments,
                        )
                        logger.info(
                            "job=%s posted_pr_review repo=%s pr=%s comments=%s",
                            job_id,
                            pr.full_name,
                            pr.number,
                            len(built.review_comments),
                        )
                    except Exception as e:
                        review_failed = str(e)
                        logger.warning(
                            "job=%s failed_post_pr_review repo=%s pr=%s err=%s",
                            job_id,
                            pr.full_name,
                            pr.number,
                            review_failed,
                        )

                if built.skipped or review_failed:
                    lines = [summary, "", "## Unplaced items (not on diff hunks / truncated):"]
                    if review_failed:
                        lines.insert(2, f"Review API failed, fallback to issue comment: `{review_failed}`")
                        # If review failed, treat all issues as unplaced.
                        built_skipped = list(confirmed_issues)
                    else:
                        built_skipped = built.skipped

                    for item in built_skipped[:200]:
                        fp = item.get("file_path", "unknown")
                        ln = item.get("line_number", "")
                        sev = item.get("severity", "info")
                        desc = (item.get("description", "") or "").strip()
                        lines.append(f"- `{fp}` `{ln}` **{sev}**: {desc}")

                    await self._deps.github.create_issue_comment(
                        owner=pr.owner,
                        repo=pr.repo,
                        pr_number=pr.number,
                        body="\n".join(lines)[:65000],
                    )
                    logger.info(
                        "job=%s posted_issue_comment repo=%s pr=%s items=%s",
                        job_id,
                        pr.full_name,
                        pr.number,
                        min(len(built_skipped), 200),
                    )

                self._deps.store.mark_done(job_id)
                logger.info("job=%s done repo=%s pr=%s", job_id, pr.full_name, pr.number)
            finally:
                if not settings.keep_worktree:
                    self._deps.repo_cache.remove_worktree(
                        mirror_dir=cache_paths.mirror_dir,
                        lock_path=cache_paths.lock_path,
                        work_dir=work_dir,
                    )
        except Exception as e:
            self._deps.store.mark_failed(job_id, str(e))
            logger.exception("job=%s failed err=%s", job_id, e)
