#!/usr/bin/env python3
"""Build committed images; optionally deploy or roll back selected services."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def image_info(reference: str) -> dict:
    # Do not inspect/retain container environments or resolved configuration.
    template = ('{"id":{{json .Id}},"revision":'
                '{{json (index .Config.Labels "org.opencontainers.image.revision")}}}')
    return json.loads(subprocess.check_output(
        ['docker', 'image', 'inspect', '--format', template, reference], cwd=ROOT))


def current_images(compose: list[str], services: list[str]) -> dict[str, str]:
    images = {}
    for name in services:
        ids = subprocess.check_output([*compose, 'ps', '-a', '-q', name], cwd=ROOT).decode().split()
        if len(ids) != 1:
            raise ValueError(f'{name}: expected one existing container; use normal startup for installation.')
        images[name] = subprocess.check_output(
            ['docker', 'inspect', '--format', '{{.Image}}', ids[0]], cwd=ROOT).decode().strip()
    return images


def save_pins(path: Path, pins: dict) -> None:
    # Atomic replacement and mode 0600; persist image references, never secrets.
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        json.dump(pins, stream, indent=2)
        stream.write('\n')
    os.replace(stream.name, path)


def build_images(compose, config, services, revision, env, reuse, parser):
    overrides = {}
    for name in services:
        service = config['services'][name]
        exists = subprocess.run(['docker', 'image', 'inspect', service['image']],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if exists.returncode == 0:
            if not reuse:
                parser.error(f"Image already exists: {service['image']}. Reuse it or build a new revision.")
            if image_info(service['image'])['revision'] != revision:
                parser.error(f'{name}: existing image does not have the expected revision label.')
        else:
            overrides[name] = {'build': {'context': str(Path(service['build']['context']).relative_to(ROOT))}}
    if overrides:
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
            # Build explicitly, one service at a time; verify every requested image.
            for name in overrides:
                subprocess.run([*compose, '-f', str(override), 'build', name], cwd=ROOT, env=env, check=True)
    images = {}
    for name in services:
        image = image_info(config['services'][name]['image'])
        if image['revision'] != revision:
            raise ValueError(f'{name}: built image has an unexpected revision label.')
        images[name] = image['id']
    return images


def deploy(args, compose, config, revision, env, parser):
    path = ROOT / '.local' / 'releases' / f'{args.host}.json'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Serialize operations on this host, including builds and rollback history.
    with path.with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error(f'Another {args.host} deployment is in progress.')
        pins = json.loads(path.read_text()) if path.exists() else {'services': {}}
        active_compose = [*compose, '-f', str(path)] if path.exists() else compose
        previous = current_images(active_compose, args.services)
        if args.rollback:
            images = {}
            for name in args.services:
                prior = pins['services'].get(name, {}).get('x-release', {}).get('previous_image')
                if not prior:
                    parser.error(f'{name}: no previous image recorded.')
                images[name] = image_info(prior)['id']  # Refuse missing rollback images before mutation.
        else:
            images = build_images(compose, config, args.services, revision, env, True, parser)
        if git('rev-parse', 'HEAD') != revision or git('status', '--porcelain', '--untracked-files=normal'):
            parser.error('Source changed during preparation; commit it before deploying.')
        # A long build must not silently overwrite another operator's images.
        if current_images(active_compose, args.services) != previous:
            parser.error('Selected containers changed during preparation; retry after checking them.')
        for name, image in images.items():
            old = pins['services'].get(name, {}).get('x-release', {})
            metadata = {'revision': image_info(image)['revision'], 'status': 'pending'}
            if previous[name] != image:
                metadata['previous_image'] = previous[name]
            elif old.get('previous_image'):
                metadata['previous_image'] = old['previous_image']
            pins['services'][name] = {'image': image, 'x-release': metadata}
        save_pins(path, pins)
        try:
            subprocess.run([*compose, '-f', str(path), 'up', '-d', '--no-deps', '--no-build',
                            '--pull', 'never', '--wait', '--wait-timeout', str(args.wait_timeout),
                            *args.services], cwd=ROOT, check=True)
            if current_images([*compose, '-f', str(path)], args.services) != images:
                raise ValueError('Running images do not match the requested deployment.')
        except (subprocess.CalledProcessError, ValueError):
            for name in args.services:
                pins['services'][name]['x-release']['status'] = 'failed'
            save_pins(path, pins)
            print('Deployment failed. Previous images are retained; use --rollback for these services.', file=sys.stderr)
            raise
        for name in args.services:
            pins['services'][name]['x-release']['status'] = 'verified'
        save_pins(path, pins)
        print(f'Verified {", ".join(args.services)}; image pins and rollback references saved in {path.relative_to(ROOT)}.')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', choices=('server', 'ai'), default='server')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--deploy', action='store_true', help='Build/reuse this revision and update only the selected services')
    mode.add_argument('--rollback', action='store_true', help='Restore selected services to their previous recorded images')
    parser.add_argument('--wait-timeout', type=int, default=180, help='Deployment healthcheck timeout in seconds (default: 180)')
    parser.add_argument('services', nargs='+', help='Buildable Compose services to update')
    args = parser.parse_args()
    args.services = list(dict.fromkeys(args.services))
    if args.wait_timeout <= 0:
        parser.error('--wait-timeout must be positive.')
    if git('status', '--porcelain', '--untracked-files=normal'):
        parser.error('Commit or stash source changes before building a release.')
    revision = git('rev-parse', 'HEAD')
    env = {**os.environ, 'STACK_VERSION': revision}
    compose = ['docker', 'compose', '-f', str(ROOT / f'docker-compose.{args.host}.yml')]
    config = json.loads(subprocess.check_output([*compose, 'config', '--format', 'json'], cwd=ROOT, env=env))
    for name in args.services:
        service = config['services'].get(name, {})
        if 'build' not in service:
            parser.error(f'{name!r} is not a buildable {args.host} service')
    if args.deploy or args.rollback:
        deploy(args, compose, config, revision, env, parser)
        return
    build_images(compose, config, args.services, revision, env, False, parser)
    print(f'Built revision {revision}. To deploy with dependencies already running:')
    print(f'STACK_VERSION={revision} docker compose -f docker-compose.{args.host}.yml '
          f'up -d --no-deps --no-build --pull never {" ".join(args.services)}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, subprocess.CalledProcessError) as error:
        sys.exit(f'Release failed: {error}')
