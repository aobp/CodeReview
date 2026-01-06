from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class PullRequestInfo:
    owner: str
    repo: str
    full_name: str
    number: int
    base_ref: str
    head_sha: str


class GitHubClient:
    def __init__(self, *, token: str, api_base_url: str) -> None:
        self._token = token
        self._api_base_url = api_base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._api_base_url,
            headers={
                "Authorization": f"token {self._token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "CodeReviewBot/1.0",
            },
            timeout=60.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_pr(self, pr_url: str) -> PullRequestInfo:
        resp = await self._client.get(pr_url)
        resp.raise_for_status()
        data = resp.json()

        full_name = str(data["base"]["repo"]["full_name"])
        owner, repo = full_name.split("/", 1)
        return PullRequestInfo(
            owner=owner,
            repo=repo,
            full_name=full_name,
            number=int(data["number"]),
            base_ref=str(data["base"]["ref"]),
            head_sha=str(data["head"]["sha"]),
        )

    async def create_review(
        self,
        *,
        owner: str,
        repo: str,
        pr_number: int,
        commit_id: str,
        body: str,
        comments: list[dict[str, Any]],
    ) -> None:
        url = f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        payload: dict[str, Any] = {
            "commit_id": commit_id,
            "event": "COMMENT",
            "body": body,
            "comments": comments,
        }
        resp = await self._client.post(url, json=payload)
        resp.raise_for_status()

    async def create_issue_comment(
        self,
        *,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
    ) -> None:
        url = f"/repos/{owner}/{repo}/issues/{pr_number}/comments"
        resp = await self._client.post(url, json={"body": body})
        resp.raise_for_status()
