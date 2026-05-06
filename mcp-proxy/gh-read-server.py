"""gh_read — thin MCP server exposing a single read-only `gh` CLI tool.

Replaces @modelcontextprotocol/server-github (26 tools, ~16KB of tool defs)
with a single ~600B tool that can invoke any read operation gh supports:
repo content, issues, PRs, discussions, releases, workflow runs, gists, search.

Auth: reads GITHUB_TOKEN from env

Safety: a subcommand allowlist rejects anything that could write. Since gh's
verbs are structured (noun verb ...), a small allowlist catches write attempts
without having to parse every possible flag.
"""

import shlex
import subprocess
import sys

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gh-read")


ALLOWED: set[tuple[str, ...]] = {
    ("api",),
    ("repo", "view"),
    ("repo", "list"),
    ("pr", "view"),
    ("pr", "list"),
    ("pr", "diff"),
    ("pr", "checks"),
    ("pr", "status"),
    ("issue", "view"),
    ("issue", "list"),
    ("issue", "status"),
    ("search", "repos"),
    ("search", "issues"),
    ("search", "prs"),
    ("search", "code"),
    ("search", "commits"),
    ("release", "view"),
    ("release", "list"),
    ("workflow", "view"),
    ("workflow", "list"),
    ("run", "view"),
    ("run", "list"),
    ("gist", "view"),
    ("gist", "list"),
    ("label", "list"),
    ("ruleset", "view"),
    ("ruleset", "list"),
    ("auth", "status"),
}


def _is_allowed(tokens: list[str]) -> tuple[bool, str]:
    if not tokens:
        return False, "empty command"
    first = tokens[0]
    if (first,) in ALLOWED:
        if first == "api":
            upper = [t.upper() for t in tokens[1:]]
            for write_verb in ("-X", "--method"):
                if write_verb in tokens[1:]:
                    idx = tokens.index(write_verb, 1)
                    if idx + 1 < len(tokens) and tokens[idx + 1].upper() != "GET":
                        return False, f"gh api with non-GET method is not allowed"
            if any(t in ("POST", "PUT", "PATCH", "DELETE") for t in upper):
                return False, "gh api with write verb is not allowed"
        return True, ""
    if len(tokens) >= 2 and (tokens[0], tokens[1]) in ALLOWED:
        return True, ""
    return False, f"subcommand not in read-only allowlist: {' '.join(tokens[:2])}"


@mcp.tool()
def gh_read(args: str) -> dict:
    """Run a read-only `gh` (GitHub CLI) command and return its output.

    Use this for anything on GitHub: reading repo files, issues, PRs,
    discussions, releases, workflow runs, gists, search. Pass the arguments
    exactly as you would type them after `gh`.

    Examples:
      - args="repo view owner/repo --json name,description,defaultBranchRef"
      - args="issue list --repo owner/repo --state open --limit 20 --json number,title,labels"
      - args="pr view 42 --repo owner/repo --json title,body,files,comments"
      - args="api 'repos/owner/repo/contents/path/to/file.py' --jq .content"
      - args="api graphql -f query='query { repository(owner:\\"o\\", name:\\"r\\") { discussions(first:5){nodes{title body}} } }'"
      - args="search issues 'is:open label:bug repo:owner/repo' --limit 10"

    Only read operations are permitted (the server enforces an allowlist). Use
    `--json` for structured output whenever you need fields rather than a
    human-readable view. Prefer narrow `--json` projections over full dumps to
    keep responses small.
    """
    try:
        tokens = shlex.split(args)
    except ValueError as e:
        return {"error": f"could not parse args: {e}"}

    ok, reason = _is_allowed(tokens)
    if not ok:
        return {"error": reason, "hint": "read-only allowlist rejected this command"}

    try:
        result = subprocess.run(
            ["gh", *tokens],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        return {"error": "gh CLI not installed in the mcp-proxy container"}
    except subprocess.TimeoutExpired:
        return {"error": "gh command timed out after 30s"}

    return {
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


if __name__ == "__main__":
    mcp.run()
