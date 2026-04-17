"""Fetch issues and PRs from a GitHub repo updated in the last N days."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from .config import GITHUB_REPO, GITHUB_TOKEN

log = logging.getLogger(__name__)

_BASE = "https://api.github.com"
_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
_PAGE_SIZE = 100


def _fetch_items(endpoint: str, since: datetime) -> list[dict]:
    items: list[dict] = []
    page = 1
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    with httpx.Client(headers=_HEADERS, timeout=30) as client:
        while True:
            resp = client.get(
                f"{_BASE}/repos/{GITHUB_REPO}/{endpoint}",
                params={"state": "all", "sort": "updated", "direction": "desc", "since": since_str, "per_page": _PAGE_SIZE, "page": page},
            )
            resp.raise_for_status()
            batch: list[dict] = resp.json()

            if not batch:
                break

            items.extend(batch)

            if len(batch) < _PAGE_SIZE:
                break
            page += 1

    return items


def fetch_activity(days: int = 7) -> dict[str, list[dict]]:
    """Return {"issues": [...], "prs": [...]} updated in the last `days` days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # /issues returns both issues and PRs; filter by presence of pull_request key
    raw = _fetch_items("issues", since)

    issues = [i for i in raw if "pull_request" not in i]
    prs = [i for i in raw if "pull_request" in i]

    log.info("Fetched %d issues and %d PRs from %s", len(issues), len(prs), GITHUB_REPO)
    return {"issues": issues, "prs": prs}


def format_transcript(activity: dict[str, list[dict]]) -> str:
    lines: list[str] = []

    if activity["prs"]:
        lines.append("## Pull Requests")
        for pr in activity["prs"]:
            state = pr["state"].upper()
            merged = pr.get("pull_request", {}).get("merged_at")
            if merged:
                state = "MERGED"
            author = pr.get("user", {}).get("login", "unknown")
            lines.append(f"[{state}] #{pr['number']} {pr['title']} (@{author})")
            if pr.get("body"):
                # First 300 chars of body for context
                body = pr["body"].strip()[:300].replace("\n", " ")
                lines.append(f"  {body}")

    if activity["issues"]:
        lines.append("\n## Issues")
        for issue in activity["issues"]:
            state = issue["state"].upper()
            author = issue.get("user", {}).get("login", "unknown")
            lines.append(f"[{state}] #{issue['number']} {issue['title']} (@{author})")
            if issue.get("body"):
                body = issue["body"].strip()[:300].replace("\n", " ")
                lines.append(f"  {body}")

    return "\n".join(lines)
