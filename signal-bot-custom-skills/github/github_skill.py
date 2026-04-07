"""GitHub repository exploration via GitHub REST API."""

import base64
import os
import httpx
from strands import tool

_TOKEN = os.getenv("GITHUB_TOKEN", "")
_BASE = "https://api.github.com"


def _gh(path: str, params: dict = None, timeout: int = 15) -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if _TOKEN:
        headers["Authorization"] = f"Bearer {_TOKEN}"
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(f"{_BASE}{path}", headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()


@tool
def get_file(repo: str, path: str, ref: str = "HEAD") -> str:
    """Get the contents of a file from a GitHub repository.

    Use when the user wants to read a specific file from a repo.

    Args:
        repo: Repository in owner/repo format (e.g. 'torvalds/linux').
        path: File path within the repository (e.g. 'README.md').
        ref: Branch, tag, or commit SHA. Defaults to HEAD.
    """
    try:
        data = _gh(f"/repos/{repo}/contents/{path}", params={"ref": ref})
        if data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return data.get("content", str(data))
    except Exception as e:
        return f"get_file failed: {e}"


@tool
def search_code(query: str, repo: str = "") -> str:
    """Search for code across GitHub by content.

    Use when the user wants to find where something is implemented or used.

    Args:
        query: Search query (e.g. 'signal receive timeout').
        repo: Optionally restrict to a specific repo in owner/repo format.
    """
    try:
        q = f"{query} repo:{repo}" if repo else query
        data = _gh("/search/code", params={"q": q, "per_page": 10})
        items = data.get("items", [])
        if not items:
            return "No results found."
        lines = []
        for i in items:
            lines.append(f"{i['repository']['full_name']}: {i['path']}\n  {i.get('html_url','')}")
        return "\n".join(lines)
    except Exception as e:
        return f"search_code failed: {e}"


@tool
def search_repos(query: str) -> str:
    """Search for GitHub repositories by name or description.

    Use when the user wants to find repositories related to a topic.

    Args:
        query: Search query (e.g. 'signal cli python').
    """
    try:
        data = _gh("/search/repositories", params={"q": query, "per_page": 8, "sort": "stars"})
        items = data.get("items", [])
        if not items:
            return "No repositories found."
        lines = []
        for r in items:
            lines.append(f"{r['full_name']} ★{r['stargazers_count']}\n  {r.get('description','')}\n  {r['html_url']}")
        return "\n\n".join(lines)
    except Exception as e:
        return f"search_repos failed: {e}"


@tool
def list_commits(repo: str, max_count: int = 10) -> str:
    """List recent commits for a GitHub repository.

    Use when the user wants to see recent changes or history of a repo.

    Args:
        repo: Repository in owner/repo format.
        max_count: Number of commits to return (default 10).
    """
    try:
        data = _gh(f"/repos/{repo}/commits", params={"per_page": max_count})
        lines = []
        for c in data:
            sha = c["sha"][:7]
            msg = c["commit"]["message"].splitlines()[0]
            author = c["commit"]["author"]["name"]
            date = c["commit"]["author"]["date"][:10]
            lines.append(f"{sha} {date} {author}: {msg}")
        return "\n".join(lines)
    except Exception as e:
        return f"list_commits failed: {e}"


@tool
def get_issue(repo: str, issue_number: int) -> str:
    """Get details of a GitHub issue or pull request.

    Use when the user references a specific issue number in a repo.

    Args:
        repo: Repository in owner/repo format.
        issue_number: The issue or PR number.
    """
    try:
        i = _gh(f"/repos/{repo}/issues/{issue_number}")
        comments = ""
        if i.get("comments", 0) > 0:
            c_data = _gh(f"/repos/{repo}/issues/{issue_number}/comments", params={"per_page": 5})
            comments = "\n\n" + "\n---\n".join(f"{c['user']['login']}: {c['body'][:300]}" for c in c_data)
        return f"#{i['number']} [{i['state']}] {i['title']}\n{i.get('body','')[:500]}{comments}"
    except Exception as e:
        return f"get_issue failed: {e}"
