#!/usr/bin/env python3
"""Validate Compose with example settings, isolated from local credentials."""

import os
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def check_security(config, host):
    services = config['services']
    def networks(name):
        return set(services[name].get('networks', {}))
    if host == 'server':
        proxy = services['mcp-proxy']
        if proxy.get('env_file') or '--pass-environment' in proxy.get('command', []):
            raise ValueError('MCP proxy must not inherit the deployment environment')
        if not proxy['environment'].get('MCP_PROXY_AUTH_TOKEN'):
            raise ValueError('MCP proxy authentication is required')
        location = services['location-tracker']
        if location.get('env_file') or any(key in location['environment'] for key in
                                          ('MEMORY_API_TOKEN', 'GITHUB_TOKEN', 'GOOGLE_MAPS_API_KEY')):
            raise ValueError('Location tool must receive only its own credentials')
        if not proxy.get('read_only') or set(proxy.get('cap_add', [])) != {'SETUID', 'SETGID'}:
            raise ValueError('MCP broker requires a read-only root and only identity-drop capabilities')
        for tool in ('mcp-proxy', 'searxng', 'browser-agent-api', 'pdf-inspector', 'reverse-image-search'):
            for store in ('mongodb', 'nextcloud-db', 'nextcloud-redis'):
                if networks(tool) & networks(store):
                    raise ValueError(f'{tool} shares a private data-store network with {store}')
        for client in ('librechat', 'signal-bot'):
            mounts = services[client].get('volumes', [])
            if any(m['target'] == '/memory' for m in mounts):
                raise ValueError(f'{client} must not mount raw vector storage')
            for name in ('SOUL.md', 'USER.md', 'MEMORY.md'):
                mount = next(m for m in mounts if m['target'] == f'/memory/{name}')
                if not mount.get('read_only') or mount.get('bind', {}).get('create_host_path', True):
                    raise ValueError(f'{client}: prompt files must exist and be read-only')
    else:
        if networks('qdrant') & networks('audio-api'):
            raise ValueError('Qdrant must be isolated from inference-facing services')
        if not config['networks']['memory-store-net'].get('internal'):
            raise ValueError('The memory-store network must remain internal')
        if not networks('qdrant') - networks('memory-mcp'):
            raise ValueError('Qdrant needs a separate bridge to publish loopback administration')
        if any(port.get('host_ip') != '127.0.0.1' for port in services['qdrant'].get('ports', [])):
            raise ValueError('Direct vector-store management must remain host-local')


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
        for example in (checkout / "examples/env").glob("*.env.example"):
            shutil.copyfile(example, checkout / example.with_suffix("").name)
        shutil.copyfile(checkout / ".env.example", checkout / ".env")
        for host in ("server", "ai"):
            name = f"docker-compose.{host}.yml"
            command = ["docker", "compose", "--env-file", str(checkout / ".env"), "-f", name]
            config = json.loads(subprocess.check_output(
                [*command, "config", "--format", "json"], cwd=checkout, env=env))
            check_security(config, host)
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
                            or relative in {"shared", "services/signal-bot/skills", "services/voice-agent/static", "nextcloud/hooks"}):
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
