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
        (self.root / '.gitignore').write_text('.env\n')
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


if __name__ == '__main__':
    unittest.main()
