"""gh_read — thin MCP server exposing a single read-only `gh` CLI tool.

Replaces @modelcontextprotocol/server-github (26 tools, ~16KB of tool defs)
with a single ~600B tool that can invoke any read operation gh supports:
repo content, issues, PRs, discussions, releases, workflow runs, gists, search.

Auth: reads GITHUB_TOKEN from env

Safety: a subcommand allowlist rejects anything that could write. Since gh's
verbs are structured (noun verb ...), a small allowlist catches write attempts
without having to parse every possible flag.
"""

import os
import re
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
}


def _is_allowed(tokens: list[str]) -> tuple[bool, str]:
    if not tokens:
        return False, "empty command"
    if tokens[0] == "api":
        # REST GET only; no field, file, hostname, header or method flags.
        if len(tokens) != 2 or not re.fullmatch(r"[A-Za-z0-9_/.-]+(?:\?[^\s#]*)?", tokens[1]):
            return False, "api accepts only one relative REST endpoint; no flags"
        endpoint = tokens[1].split("?", 1)[0]
        if endpoint.startswith(("/", ".")) or ".." in endpoint or endpoint.split("/", 1)[0] == "graphql":
            return False, "only relative REST endpoints are permitted"
        return True, ""
    if len(tokens) < 2 or tuple(tokens[:2]) not in ALLOWED:
        return False, "subcommand not in read-only allowlist"
    # No debug/token flags, templates, file flags, web launch or host override.
    value_flags = {"--json", "--repo", "-R", "--limit", "-L", "--state",
                   "--author", "--assignee", "--label", "--base", "--head",
                   "--sort", "--order", "--language", "--owner", "--visibility",
                   "--created", "--updated", "--match", "--filename", "--extension"}
    switches = {"--comments", "--patch", "--include-forks", "--archived"}
    i = 2
    while i < len(tokens):
        token = tokens[i]
        if token in switches:
            i += 1
            continue
        flag, sep, value = token.partition("=")
        if flag in value_flags:
            if not sep:
                i += 1
                if i >= len(tokens):
                    return False, "missing flag value"
                value = tokens[i]
            if flag in {"--repo", "-R"} and not re.fullmatch(r"[\w.-]+/[\w.-]+", value):
                return False, "repository must be owner/name on github.com"
        else:
            if token.startswith("-") or "://" in token:
                return False, "unsupported flag or URL"
            if tuple(tokens[:2]) == ("repo", "view") and not re.fullmatch(r"[\w.-]+/[\w.-]+", token):
                return False, "repository must be owner/name on github.com"
            if tuple(tokens[:2]) == ("repo", "list") and not re.fullmatch(r"[\w.-]+", token):
                return False, "owner must be a github.com account name"
        i += 1
    return True, ""


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
      - args="api repos/owner/repo/contents/path/to/file.py"
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
            ["gh", *tokens, "--method", "GET"] if tokens[0] == "api" else ["gh", *tokens],
            env={**{k: v for k, v in os.environ.items() if k not in {"GH_DEBUG", "DEBUG", "GH_HOST"}},
                 "GH_HOST": "github.com", "GH_PROMPT_DISABLED": "1"},
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
