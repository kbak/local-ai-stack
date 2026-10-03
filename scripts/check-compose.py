#!/usr/bin/env python3
"""Validate Compose with example settings, isolated from local credentials."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
    ).decode().split("\0")
    # Compose interpolation must not inherit deployment values from the caller.
    env = {key: os.environ[key] for key in ("PATH", "HOME", "DOCKER_CONFIG") if key in os.environ}
    with tempfile.TemporaryDirectory(prefix="stack-compose-") as directory:
        checkout = Path(directory)
        for name in sorted(set(names)):
            source = ROOT / name
            if not name or not source.is_file():
                continue
            if source.is_symlink() or source.name == ".env" or source.name.endswith(".env"):
                raise ValueError(f"Local file must not be tracked: {name}")
            target = checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        for example in checkout.glob("*.env.example"):
            shutil.copyfile(example, example.with_suffix(""))
        shutil.copyfile(checkout / ".env.example", checkout / ".env")
        for name in ("docker-compose.server.yml", "docker-compose.ai.yml"):
            subprocess.run(
                ["docker", "compose", "--env-file", str(checkout / ".env"),
                 "-f", name, "config", "--quiet"],
                cwd=checkout, env=env, check=True,
            )
            print(f"{name}: valid with example configuration")


if __name__ == "__main__":
    main()
