"""Contracts for manifest discovery and sequential polling, without live services."""

import logging
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'shared'))
from stack_shared import polling, skills


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        previous_path = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), previous_path))
        before = set(sys.modules)
        self.addCleanup(lambda: [sys.modules.pop(k, None) for k in set(sys.modules) - before
                                 if k.startswith('custom_skills.')])

    def skill(self, name, *, runtimes='', extra=''):
        directory = self.root / name
        directory.mkdir()
        (directory / 'skill.yaml').write_text(
            f'name: {name}\ntools: ["entry:first", "entry:second"]\n' + runtimes + extra)
        (directory / 'entry.py').write_text('''
loaded = object()
def first(): return loaded
def second(): return loaded
first.tool_spec = {'name': 'first'}
second.TOOL_SPEC = {'name': 'second'}
''')
        return directory

    def test_declared_tools_only_and_shared_module_instance(self):
        directory = self.skill('declared')
        (directory / 'test_unlisted.py').write_text('raise RuntimeError("must never import")')
        tools, names = skills.discover(self.root, 'voice')
        self.assertEqual(names, ['declared'])
        self.assertEqual([tool.__name__ for tool in tools], ['first', 'second'])
        self.assertIs(tools[0](), tools[1]())
        self.assertIs(skills.load_tool(directory, 'entry:first'), tools[0])

    def test_runtime_restriction_prevents_import(self):
        directory = self.skill('signal_only', runtimes='runtimes: [signal]\n')
        (directory / 'entry.py').write_text('raise RuntimeError("wrong runtime")')
        self.assertEqual(skills.discover(self.root, 'voice'), ([], []))
        self.assertIsNotNone(skills.read_manifest(directory, 'signal'))

    def test_disabled_and_unmanifested_directories_are_not_imported(self):
        self.skill('disabled', extra='enabled: false\n')
        directory = self.root / 'unmanifested'; directory.mkdir()
        (directory / 'entry.py').write_text('raise RuntimeError("unlisted")')
        self.assertEqual(skills.discover(self.root, 'signal'), ([], []))

    def test_identical_module_names_do_not_collide(self):
        one = self.skill('one'); two = self.skill('two')
        self.assertIsNot(skills.load_tool(one, 'entry:first')(), skills.load_tool(two, 'entry:first')())

    def test_failed_import_is_removed_and_can_be_retried(self):
        directory = self.skill('retry')
        original = (directory / 'entry.py').read_text()
        (directory / 'entry.py').write_text('raise RuntimeError("broken import")')
        with self.assertRaisesRegex(RuntimeError, 'broken import'):
            skills.load_tool(directory, 'entry:first')
        self.assertNotIn('custom_skills.retry.entry', sys.modules)
        (directory / 'entry.py').write_text(original)
        self.assertTrue(callable(skills.load_tool(directory, 'entry:first')))

    def test_broken_skill_does_not_hide_other_tools(self):
        self.skill('good')
        directory = self.skill('broken')
        (directory / 'entry.py').write_text('raise RuntimeError("broken import")')
        with self.assertLogs(skills.log, level='ERROR'):
            tools, names = skills.discover(self.root, 'voice')
        self.assertEqual(names, ['good'])
        self.assertEqual(len(tools), 2)

    def test_invalid_references_and_plain_functions_are_rejected(self):
        directory = self.skill('invalid')
        for ref in ['../entry:first', 'entry:_private', 'entry:first:extra', None]:
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                skills.load_tool(directory, ref)
        (directory / 'entry.py').write_text('def first(): return None')
        with self.assertRaises(TypeError):
            skills.load_tool(directory, 'entry:first')


class StopPolling(BaseException):
    pass


class PollingTests(unittest.TestCase):
    def test_immediate_poll_and_delay_after_success_or_failure(self):
        events = []
        def poll():
            events.append('poll')
            if events.count('poll') == 1:
                raise ValueError('transient')
        def sleep(seconds):
            events.append(('sleep', seconds))
            if events.count('poll') == 2:
                raise StopPolling()
        log = logging.getLogger('test-polling')
        with patch.object(polling.time, 'sleep', side_effect=sleep):
            with self.assertLogs(log, level='INFO') as logs, self.assertRaises(StopPolling):
                polling.run_polling(poll, 60, logger=log, poll_message='Polling', error_message='Failed')
        self.assertEqual(events, ['poll', ('sleep', 60), 'poll', ('sleep', 60)])
        self.assertTrue(any('Failed' in message for message in logs.output))

    def test_shutdown_is_not_swallowed_or_delayed(self):
        def poll(): raise KeyboardInterrupt()
        with patch.object(polling.time, 'sleep') as sleep:
            with self.assertRaises(KeyboardInterrupt):
                polling.run_polling(poll, 60, logger=logging.getLogger('test-polling'))
            sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
