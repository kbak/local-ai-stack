#!/usr/bin/env python3
"""Build selected service images from a clean, archived Git revision."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', choices=('server', 'ai'), default='server')
    parser.add_argument('services', nargs='+', help='Compose services to build')
    args = parser.parse_args()
    if git('status', '--porcelain', '--untracked-files=normal'):
        parser.error('Commit or stash source changes before building a release.')
    revision = git('rev-parse', 'HEAD')
    env = {**os.environ, 'STACK_VERSION': revision}
    compose = ['docker', 'compose', '-f', str(ROOT / f'docker-compose.{args.host}.yml')]
    config = json.loads(subprocess.check_output([*compose, 'config', '--format', 'json'], cwd=ROOT, env=env))
    overrides = {}
    for name in args.services:
        service = config['services'].get(name, {})
        if 'build' not in service:
            parser.error(f'{name!r} is not a buildable {args.host} service')
        # Never overwrite a published revision tag with a different rebuild.
        exists = subprocess.run(['docker', 'image', 'inspect', service['image']],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if exists.returncode == 0:
            parser.error(f"Image already exists: {service['image']}. Reuse it or build a new revision.")
        overrides[name] = {'build': {'context': str(Path(service['build']['context']).relative_to(ROOT))}}
    with tempfile.TemporaryDirectory(prefix='stack-release-') as directory:
        root = Path(directory)
        archive = root / 'source.tar'
        subprocess.run(['git', 'archive', '--format=tar', '-o', str(archive), revision], cwd=ROOT, check=True)
        source = root / 'source'
        source.mkdir()
        with tarfile.open(archive) as bundle:
            bundle.extractall(source, filter='data')
        for service in overrides.values():
            service['build']['context'] = str(source / service['build']['context'])
            service['build']['args'] = {'STACK_REVISION': revision}
            service['build']['labels'] = {'org.opencontainers.image.revision': revision}
        override = root / 'build.json'
        override.write_text(json.dumps({'services': overrides}))
        subprocess.run([*compose, '-f', str(override), 'build', *args.services], cwd=ROOT, env=env, check=True)
    print(f'Built revision {revision}. To deploy with dependencies already running:')
    print(f'STACK_VERSION={revision} docker compose -f docker-compose.{args.host}.yml '
          f'up -d --no-deps --no-build --pull never {" ".join(args.services)}')


if __name__ == '__main__':
    main()
