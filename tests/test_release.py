"""Release builds use committed source and never include local deployment files."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_release', ROOT / 'scripts/build-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / '.gitignore').write_text('.env\n.local/\n')
        (self.root / 'app.py').write_text('print("committed")\n')
        subprocess.run(['git', 'add', '.'], cwd=self.root, check=True)
        subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                        '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture'], cwd=self.root, check=True)
        (self.root / '.env').write_text('PRIVATE_VALUE=must-not-enter-context\n')
        root_patch = patch.object(release, 'ROOT', self.root)
        root_patch.start(); self.addCleanup(root_patch.stop)
        argv_patch = patch('sys.argv', ['build-release.py', 'demo'])
        argv_patch.start(); self.addCleanup(argv_patch.stop)

    def test_archive_excludes_local_files_and_build_is_revision_tagged(self):
        original_run = subprocess.run
        original_output = subprocess.check_output
        built = []
        def output(command, **kwargs):
            if command[0] != 'docker':
                return original_output(command, **kwargs)
            if command[1:3] == ['image', 'inspect']:
                return json.dumps({'id': 'sha256:built', 'revision': release.git('rev-parse', 'HEAD')}).encode()
            self.assertEqual(command[-3:], ['config', '--format', 'json'])
            revision = kwargs['env']['STACK_VERSION']
            return json.dumps({'services': {'demo': {
                'image': 'local-ai-stack/demo:' + revision,
                'build': {'context': str(self.root)},
            }}}).encode()
        def run(command, **kwargs):
            if command[0] != 'docker':
                return original_run(command, **kwargs)
            if command[1:3] == ['image', 'inspect']:
                return subprocess.CompletedProcess(command, 1)
            override = Path(command[command.index('build') - 1])
            build = json.loads(override.read_text())['services']['demo']['build']
            context = Path(build['context'])
            self.assertFalse((context / '.env').exists())
            self.assertEqual((context / 'app.py').read_text(), 'print("committed")\n')
            self.assertEqual(build['labels']['org.opencontainers.image.revision'], kwargs['env']['STACK_VERSION'])
            self.assertNotEqual(context, self.root)
            built.append(context)
            return subprocess.CompletedProcess(command, 0)
        with patch.object(release.subprocess, 'check_output', side_effect=output), \
             patch.object(release.subprocess, 'run', side_effect=run), patch('builtins.print'):
            release.main()
        self.assertEqual(len(built), 1)
        self.assertFalse(built[0].exists())

    def test_dirty_source_is_rejected_before_docker(self):
        (self.root / 'app.py').write_text('print("uncommitted")\n')
        with patch('sys.stderr'), self.assertRaises(SystemExit) as error:
            release.main()
        self.assertEqual(error.exception.code, 2)

    def test_existing_revision_tag_is_not_overwritten(self):
        original_output = subprocess.check_output
        original_run = subprocess.run
        def output(command, **kwargs):
            if command[0] != 'docker': return original_output(command, **kwargs)
            return json.dumps({'services': {'demo': {
                'image': 'local-ai-stack/demo:existing', 'build': {'context': str(self.root)},
            }}}).encode()
        docker_commands = []
        def run(command, **kwargs):
            if command[0] != 'docker': return original_run(command, **kwargs)
            docker_commands.append(command)
            return subprocess.CompletedProcess(command, 0)
        with patch.object(release.subprocess, 'check_output', side_effect=output), \
             patch.object(release.subprocess, 'run', side_effect=run), \
             patch('sys.stderr'), self.assertRaises(SystemExit):
            release.main()
        self.assertEqual(docker_commands, [['docker', 'image', 'inspect', 'local-ai-stack/demo:existing']])

    def fake_deployment(self):
        """Fake Docker only; use real Git archives, revisions and private pin files."""
        self.running = {'demo': 'sha256:old-demo', 'other': 'sha256:old-other'}
        self.images = {image: {'id': image, 'revision': None} for image in self.running.values()}
        self.built = []
        self.updated = []
        self.fail_health = False
        original_output = subprocess.check_output
        original_run = subprocess.run

        def output(command, **kwargs):
            if command[0] != 'docker':
                return original_output(command, **kwargs)
            if command[1:3] == ['image', 'inspect']:
                reference = command[-1]
                if reference not in self.images:
                    raise subprocess.CalledProcessError(1, command)
                return json.dumps(self.images[reference]).encode()
            if command[1] == 'inspect':
                return self.running[command[-1].removesuffix('-container')].encode()
            if command[-3:] == ['config', '--format', 'json']:
                revision = kwargs['env']['STACK_VERSION']
                return json.dumps({'services': {name: {
                    'image': f'example/{name}:{revision}',
                    'build': {'context': str(self.root)},
                    'environment': {'PRIVATE_VALUE': 'must-not-be-recorded'},
                } for name in self.running}}).encode()
            if 'ps' in command:
                return f'{command[-1]}-container'.encode()
            self.fail(f'Unexpected Docker command: {command}')

        def run(command, **kwargs):
            if command[0] != 'docker':
                return original_run(command, **kwargs)
            if command[1:3] == ['image', 'inspect']:
                return subprocess.CompletedProcess(command, 0 if command[-1] in self.images else 1)
            if 'build' in command:
                name = command[-1]
                override = json.loads(Path(command[command.index('build') - 1]).read_text())
                context = Path(override['services'][name]['build']['context'])
                self.assertFalse((context / '.env').exists())
                self.assertFalse((context / '.local').exists())
                revision = kwargs['env']['STACK_VERSION']
                info = {'id': f'sha256:{name}-{revision}', 'revision': revision}
                self.images[f'example/{name}:{revision}'] = info
                self.images[info['id']] = info
                self.built.append(name)
            elif 'up' in command:
                self.assertIn('--no-deps', command)
                self.assertIn('--no-build', command)
                self.assertEqual(command[command.index('--pull') + 1], 'never')
                self.assertIn('--wait', command)
                self.assertNotIn('env', kwargs)  # No global STACK_VERSION change on deployment.
                pins = json.loads(Path(command[command.index('up') - 1]).read_text())
                names = command[command.index('--wait-timeout') + 2:]
                self.updated.append(names)
                for name in names:
                    self.running[name] = pins['services'][name]['image']
                if self.fail_health:
                    raise subprocess.CalledProcessError(1, command)
            else:
                self.fail(f'Unexpected Docker command: {command}')
            return subprocess.CompletedProcess(command, 0)

        self.enterContext(patch.object(release.subprocess, 'check_output', side_effect=output))
        self.enterContext(patch.object(release.subprocess, 'run', side_effect=run))
        self.enterContext(patch('builtins.print'))
        return self.root / '.local/releases/server.json'

    def invoke(self, *args):
        with patch('sys.argv', ['build-release.py', *args]):
            release.main()

    def test_deploy_pins_only_selected_service_and_records_previous_image_privately(self):
        path = self.fake_deployment()
        self.invoke('--deploy', 'demo')
        pins = json.loads(path.read_text())
        self.assertEqual(set(pins['services']), {'demo'})
        self.assertEqual(pins['services']['demo']['image'], self.running['demo'])
        self.assertEqual(pins['services']['demo']['x-release']['previous_image'], 'sha256:old-demo')
        self.assertEqual(pins['services']['demo']['x-release']['status'], 'verified')
        self.assertEqual(self.running['other'], 'sha256:old-other')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('must-not-be-recorded', path.read_text())
        self.assertEqual(release.git('status', '--porcelain'), '')

    def test_independent_revisions_and_per_service_rollback(self):
        path = self.fake_deployment()
        self.invoke('--deploy', 'demo')
        first = self.running['demo']
        (self.root / 'app.py').write_text('print("next revision")\n')
        subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                        '-c', 'commit.gpgsign=false', 'commit', '-qam', 'next'], cwd=self.root, check=True)
        self.invoke('--deploy', 'other')
        other = self.running['other']
        pins = json.loads(path.read_text())['services']
        self.assertEqual(pins['demo']['image'], first)
        self.assertNotEqual(pins['demo']['x-release']['revision'], pins['other']['x-release']['revision'])
        self.invoke('--rollback', 'demo')
        self.assertEqual(self.running['demo'], 'sha256:old-demo')
        self.assertEqual(self.running['other'], other)
        self.assertEqual(self.built, ['demo', 'other'])  # Rollback never rebuilds.

    def test_failed_deploy_and_retry_keep_known_previous_image(self):
        path = self.fake_deployment()
        self.fail_health = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.invoke('--deploy', 'demo')
        self.assertEqual(json.loads(path.read_text())['services']['demo']['x-release']['status'], 'failed')
        self.fail_health = False
        self.invoke('--deploy', 'demo')
        self.assertEqual(self.built, ['demo'])  # Reuses only the verified revision.
        self.assertEqual(json.loads(path.read_text())['services']['demo']['x-release']['previous_image'], 'sha256:old-demo')
        self.invoke('--rollback', 'demo')
        self.assertEqual(self.running['demo'], 'sha256:old-demo')

    def test_existing_image_with_wrong_revision_is_rejected(self):
        path = self.fake_deployment()
        revision = release.git('rev-parse', 'HEAD')
        self.images[f'example/demo:{revision}'] = {'id': 'sha256:unexpected', 'revision': 'different'}
        with patch('sys.stderr'), self.assertRaises(SystemExit):
            self.invoke('--deploy', 'demo')
        self.assertFalse(path.exists())
        self.assertFalse(self.updated)

    def test_rollback_without_history_does_not_change_deployment(self):
        path = self.fake_deployment()
        with patch('sys.stderr'), self.assertRaises(SystemExit):
            self.invoke('--rollback', 'demo')
        self.assertFalse(path.exists())
        self.assertFalse(self.updated)

    def test_missing_previous_image_refuses_rollback_without_changing_pins(self):
        path = self.fake_deployment()
        self.invoke('--deploy', 'demo')
        before = path.read_bytes()
        del self.images['sha256:old-demo']
        with self.assertRaises(subprocess.CalledProcessError):
            self.invoke('--rollback', 'demo')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.updated), 1)

    def test_deployment_lock_prevents_overlapping_updates(self):
        path = self.fake_deployment()
        path.parent.mkdir(parents=True)
        with path.with_suffix('.lock').open('a') as lock:
            release.fcntl.flock(lock, release.fcntl.LOCK_EX | release.fcntl.LOCK_NB)
            with patch('sys.stderr'), self.assertRaises(SystemExit):
                self.invoke('--deploy', 'demo')
        self.assertFalse(self.built)
        self.assertFalse(self.updated)

    def test_builds_every_selected_image(self):
        self.fake_deployment()
        self.invoke('--deploy', 'demo', 'other')
        self.assertEqual(self.built, ['demo', 'other'])
        self.assertEqual(self.updated, [['demo', 'other']])

    def test_source_changed_while_building_is_not_deployed(self):
        path = self.fake_deployment()
        build = release.build_images
        def concurrent_edit(*args):
            images = build(*args)
            (self.root / 'app.py').write_text('print("uncommitted edit during build")\n')
            return images
        with patch.object(release, 'build_images', side_effect=concurrent_edit), \
                patch('sys.stderr'), self.assertRaises(SystemExit):
            self.invoke('--deploy', 'demo')
        self.assertFalse(path.exists())
        self.assertFalse(self.updated)

    def test_ai_deployment_does_not_read_or_change_server_pins(self):
        path = self.fake_deployment()
        path.parent.mkdir(parents=True)
        path.write_text('{"services":{"unrelated-server-service":{"image":"leave-alone"}}}\n')
        before = path.read_bytes()
        self.invoke('--host', 'ai', '--deploy', 'demo')
        self.assertEqual(path.read_bytes(), before)
        ai_pins = json.loads(path.with_name('ai.json').read_text())
        self.assertEqual(set(ai_pins['services']), {'demo'})


if __name__ == '__main__':
    unittest.main()
