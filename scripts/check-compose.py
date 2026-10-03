#!/usr/bin/env python3
"""Validate Compose with example settings, isolated from local credentials."""

import os
import json
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
        for host in ("server", "ai"):
            name = f"docker-compose.{host}.yml"
            command = ["docker", "compose", "--env-file", str(checkout / ".env"), "-f", name]
            config = json.loads(subprocess.check_output(
                [*command, "config", "--format", "json"], cwd=checkout, env=env))
            for service in config["services"].values():
                for mount in service.get("volumes", []):
                    if mount["type"] != "bind":
                        continue
                    source = Path(mount["source"])
                    try:
                        relative = source.relative_to(checkout).as_posix()
                    except ValueError:
                        continue  # Operator data directories are runtime inputs.
                    if (source.suffix in {".py", ".js", ".sh"}
                            or relative in {"shared", "signal-bot-custom-skills", "voice-agent/static", "nextcloud/hooks"}):
                        raise ValueError(f"{name}: production mounts executable source {relative}")
            dev = json.loads(subprocess.check_output(
                [*command, "-f", f"docker-compose.{host}.dev.yml", "config", "--format", "json"],
                cwd=checkout, env=env))
            for service_name, service in config["services"].items():
                dev_mounts = {v["target"]: v for v in dev["services"][service_name].get("volumes", [])}
                for mount in service.get("volumes", []):
                    if dev_mounts.get(mount["target"]) != mount:
                        raise ValueError(f"Development override changed persistent/config mount: {service_name}")
            print(f"{name}: production and development configurations valid; data mounts preserved")



if __name__ == "__main__":
    main()
