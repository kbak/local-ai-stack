"""Patch application must fail closed when the pinned upstream source changes."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import apply_patches


class PatchTests(unittest.TestCase):
    def test_context_mismatch_leaves_all_sources_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app, site = root / 'app', root / 'site'
            files = [app / p for p in ['bot.py', 'agent.py', 'config.py', 'skills/registry.py']]
            files.append(site / 'strands/models/openai.py')
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'# Unexpected upstream revision\r\n')
            before = [p.read_bytes() for p in files]
            # The failure is from real git apply against mismatched context.
            with self.assertRaises(subprocess.CalledProcessError):
                apply_patches.apply_patches(app, site)
            self.assertEqual(before, [p.read_bytes() for p in files])

    def test_invalid_python_is_not_installed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app, site = root / 'app', root / 'site'
            files = [app / p for p in ['bot.py', 'agent.py', 'config.py', 'skills/registry.py']]
            files.append(site / 'strands/models/openai.py')
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('# original\n')
            def fake_apply(command, *, cwd, check):
                if '--check' not in command:
                    (cwd / 'bot.py').write_text('def broken(')
            with patch.object(apply_patches.subprocess, 'run', side_effect=fake_apply):
                with self.assertRaises(SyntaxError):
                    apply_patches.apply_patches(app, site)
            self.assertTrue(all(p.read_text() == '# original\n' for p in files))


if __name__ == '__main__':
    unittest.main()
