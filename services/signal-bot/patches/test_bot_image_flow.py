"""Run the patched upstream receive loop with a fake transport and no model calls."""
import ast
from collections import deque
import logging
import os
from pathlib import Path
import queue
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
import image_tools as it


class BotFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(os.environ.get('SIGNAL_BOT_TEST_SOURCE', '/app/bot.py'))
        if not source.is_file():
            raise unittest.SkipTest('Run against the built bot or set SIGNAL_BOT_TEST_SOURCE to the patched upstream bot.')
        tree = ast.parse(source.read_text())
        cls.functions = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef)
                               and node.name in ('extract_messages', 'main', '_fetch_image_b64', 'handle_direct_skill')],
                               type_ignores=[])

    def namespace(self, transport):
        import re
        namespace = {
            'config': SimpleNamespace(signal=SimpleNamespace(number='+10000000000', api_url='http://signal.test',
                       allowed_numbers=[], group_prefix='bot'), llm=SimpleNamespace(model_id='test', base_url='http://model.test'),
                       tts=SimpleNamespace(enabled=False)),
            'SignalClient': Mock(return_value=transport), 'logger': logging.getLogger('bot-flow-test'),
            'create_agent': Mock(), 'get_agent': Mock(), 'get_registry': Mock(return_value=SimpleNamespace(skills=[], tools=[])),
            'threading': SimpleNamespace(Thread=Mock()), '_worker': Mock(), 'start_scheduler': Mock(),
            'time': SimpleNamespace(sleep=Mock()),
            'POLL_INTERVAL': 1, '_GROUP_HISTORY_MAX': 30, 'deque': deque, 're': re, 'httpx': httpx,
            '_group_history': {}, '_group_history_count': {}, '_group_last_seen': {}, '_work_queue': queue.Queue(),
            'AUDIO_CONTENT_TYPES': {'audio/ogg'}, 'PDF_CONTENT_TYPES': {'application/pdf'},
            'MAX_IMAGE_BYTES': 20 * 1024 * 1024, '_IMAGE_FORMAT': {'image/jpeg': 'jpeg'},
            'remember_image_message': it.remember_image_message, 'select_message_images': it.select_message_images,
            'fetch_message_images': it.fetch_message_images, 'reply_context': it.reply_context,
            'handle_slash_command': Mock(return_value=False),
        }
        exec(compile(self.functions, '<patched-bot>', 'exec'), namespace)
        return namespace

    def test_ignored_group_upload_is_resolved_by_a_later_prefix_reply(self):
        transport = Mock()
        transport.is_healthy.return_value = True
        def envelope(message, timestamp, **data):
            return {'envelope': {'source': 'sender-a', 'sourceNumber': '+10000000001', 'sourceUuid': 'uuid-a',
                    'timestamp': timestamp, 'dataMessage': {'message': message, 'groupInfo': {'groupId': 'group-a'}, **data}}}
        transport.receive.side_effect = [[
            envelope('original caption', 100, attachments=[{'id': 'original', 'contentType': 'image/jpeg'}]),
            envelope('bot what is this?', 200, quote={'id': 100, 'authorUuid': 'uuid-a', 'text': 'original caption'}),
        ], KeyboardInterrupt]
        namespace = self.namespace(transport)
        namespace['handle_direct_skill'] = Mock(return_value=False)
        namespace['_fetch_image_b64'] = Mock(return_value={'image': {'format': 'jpeg', 'source': {'bytes': b'image'}}})
        with tempfile.TemporaryDirectory() as folder, patch.object(it, 'ROOT', Path(folder)):
            namespace['main']()
        self.assertEqual(namespace['_work_queue'].qsize(), 1)
        item = namespace['_work_queue'].get_nowait()
        namespace['_fetch_image_b64'].assert_called_once_with('http://signal.test', 'original', 'image/jpeg')
        self.assertTrue(item[4].selection.is_reply)
        self.assertIn('[replying to: original caption]', item[3])
        self.assertIn('what is this?', item[3])

    def test_fetch_accepts_twenty_mib_and_rejects_larger_image(self):
        namespace = self.namespace(Mock())
        for size, accepted in ((20 * 1024 * 1024, True), (20 * 1024 * 1024 + 1, False)):
            response = httpx.Response(200, content=b'x' * size, request=httpx.Request('GET', 'http://signal.test/image'))
            with patch.object(httpx, 'get', return_value=response):
                result = namespace['_fetch_image_b64']('http://signal.test', 'image', 'image/jpeg')
            self.assertEqual(result is not None, accepted)

    def test_direct_queue_keeps_missing_quote_selection(self):
        namespace = self.namespace(Mock())
        registry = SimpleNamespace(commands={'/identify': SimpleNamespace(arg_name='source', usage='identify')})
        namespace['get_registry'] = Mock(return_value=registry)
        images = it.ImageBlocks(it.ImageSelection([], is_reply=True))
        self.assertTrue(namespace['handle_direct_skill']('/identify', 'latest', Mock(), 'group-a', images))
        self.assertIs(namespace['_work_queue'].get_nowait()[6], images)


if __name__ == '__main__':
    unittest.main()
