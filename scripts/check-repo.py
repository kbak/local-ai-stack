#!/usr/bin/env python3
"""Check public source syntax, local documentation links, and repository hygiene."""

import ast
import json
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]


def public_files() -> list[Path]:
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
    ).decode().split("\0")
    return sorted({ROOT / p for p in paths if p and (ROOT / p).is_file()})


def main() -> int:
    errors = []
    files = public_files()
    credential = re.compile(
        r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|"
        r"AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
    )
    for path in files:
        name = path.relative_to(ROOT).as_posix()
        if (path.name == ".env" or path.name.endswith(".env")
                or name.startswith((".local/", ".deployment/", ".maintenance/"))):
            errors.append(f"{name}: local deployment file is tracked")
        try:
            source = path.read_text()
        except UnicodeDecodeError:
            continue
        if credential.search(source):
            errors.append(f"{name}: possible credential (value withheld)")
        if path.name == "Dockerfile":
            stages = set()
            for line in source.splitlines():
                match = re.match(r"FROM\s+(\S+)(?:\s+AS\s+(\S+))?", line, re.I)
                copy = re.match(r"COPY\s+--from=(\S+)", line, re.I)
                reference = match[1] if match else copy[1] if copy else None
                if (reference and reference not in stages and reference != "scratch"
                        and not reference.isdigit()
                        and not re.search(r"@sha256:[a-f0-9]{64}$", reference)):
                    errors.append(f"{name}: unpinned external image {reference}")
                if match and match[2]:
                    stages.add(match[2])
        try:
            if path.suffix == ".py":
                ast.parse(source, filename=name)
            elif path.suffix == ".json":
                json.loads(source)
            elif path.suffix == ".toml":
                tomllib.loads(source)
            elif path.suffix == ".sh":
                subprocess.run(["bash", "-n", str(path)], check=True, capture_output=True)
            elif path.suffix in {".js", ".cjs"}:
                subprocess.run(["node", "--check", str(path)], check=True, capture_output=True)
        except (SyntaxError, ValueError, subprocess.CalledProcessError) as exc:
            errors.append(f"{name}: syntax check failed ({type(exc).__name__})")
        if path.suffix == ".md":
            prose = re.sub(r"^```.*?^```[^\n]*$", "", source, flags=re.M | re.S)
            for target in re.findall(r"\]\(([^\s)]+)\)", prose):
                if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                    continue
                relative = unquote(target.split("#", 1)[0])
                if not (path.parent / relative).exists():
                    errors.append(f"{name}: missing link target {relative}")
    for error in errors:
        print(error, file=sys.stderr)
    print(f"Checked {len(files)} public files; {len(errors)} errors.")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
