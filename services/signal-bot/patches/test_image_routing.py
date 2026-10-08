"""Message-specific image routing, including replies to unactivated group messages."""
import io
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image
import image_tools as it


def block(color='red'):
    out = io.BytesIO()
    Image.new('RGB', (8, 8), color).save(out, format='PNG')
    return {'image': {'source': {'bytes': out.getvalue()}}}


def original(timestamp=100, author='sender-a', attachment='original'):
    return {'timestamp': timestamp, 'sender': author, 'sender_aliases': [author, 'uuid-a'],
            'attachments': [{'id': attachment, 'contentType': 'image/jpeg'}]}


def reply(timestamp=100, author='uuid-a', thumbnail=None):
    quote = {'id': timestamp, 'authorUuid': author, 'text': 'quoted caption'}
    if thumbnail:
        quote['attachments'] = [{'contentType': 'image/jpeg', 'thumbnail':
                                 {'id': thumbnail, 'contentType': 'image/jpeg'}}]
    return {'quote': quote, 'attachments': []}


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = patch.object(it, 'ROOT', Path(self.temp.name))
        root.start()
        self.addCleanup(root.stop)

    def test_quote_resolves_original_by_author_timestamp_and_conversation(self):
        it.remember_image_message(original(), 'group-a')
        it.remember_image_message(original(200, attachment='newer'), 'group-a')
        self.assertEqual(it.select_message_images(reply(thumbnail='thumb'), 'group-a').attachments[0]['id'], 'original')
        # Re-reading the on-disk index works without any process-local state.
        self.assertEqual(it.select_message_images(reply(), 'group-a').attachments[0]['id'], 'original')
        self.assertEqual(it.select_message_images(reply(), 'group-b').attachments, [])
        self.assertEqual(it.select_message_images(reply(author='another-author'), 'group-a').attachments, [])
        self.assertEqual(it.select_message_images(reply(timestamp=999), 'group-a').attachments, [])

    def test_thumbnail_and_failed_original_fallback(self):
        selection = it.select_message_images(reply(thumbnail='thumb'), 'group-a')
        self.assertTrue(selection.thumbnail)
        it.remember_image_message(original(), 'group-a')
        selection = it.select_message_images(reply(thumbnail='thumb'), 'group-a')
        seen = []
        def fetch(att):
            seen.append(att['id'])
            return None if att['id'] == 'original' else block()
        images = it.fetch_message_images(selection, fetch)
        self.assertEqual(seen, ['original', 'thumb'])
        self.assertEqual(len(images), 1)
        self.assertTrue(selection.thumbnail)

    def test_new_upload_takes_precedence_over_quote(self):
        it.remember_image_message(original(), 'group-a')
        message = reply()
        message['attachments'] = original(attachment='new-upload')['attachments']
        self.assertEqual(it.select_message_images(message, 'group-a').attachments[0]['id'], 'new-upload')

    def test_index_retention_and_bound(self):
        for n in range(it.KEEP_MESSAGES + 5):
            it.remember_image_message(original(n + 1), 'group-a')
        self.assertEqual(len(it._message_index('group-a')), it.KEEP_MESSAGES)
        self.assertEqual(it.select_message_images(reply(timestamp=1), 'group-a').attachments, [])
        with patch.object(it.time, 'time', return_value=time.time() + it.RETENTION_SECONDS + 1):
            self.assertEqual(it.select_message_images(reply(timestamp=205), 'group-a').attachments, [])

    async def test_missing_quote_does_not_default_to_old_image_but_preserves_history(self):
        old_id = it._save(it._directory('group-a'), block()['image']['source']['bytes'])
        selection = it.select_message_images(reply(), 'group-a')
        async def invoke(text):
            self.assertIn('Do not silently substitute another image', text)
            with self.assertRaisesRegex(ValueError, 'No image is available'):
                it.read_conversation_image('latest')
            self.assertIn('No image is available', await it.run_image('edit it', '1024x1024', 'latest'))
            self.assertEqual(it.read_conversation_image(old_id)[0], old_id)
            return 'done'
        agent = AsyncMock()
        agent.messages = [{'role': 'user', 'content': [{'text': 'old caption'}, block()]}]
        agent.invoke_async.side_effect = invoke
        await it.invoke_with_images(agent, 'question', it.ImageBlocks(selection), None, 'group-a')
        self.assertEqual(agent.messages[0]['content'], [{'text': 'old caption'}, block()])
        self.assertIsNone(it._turn.get())

    async def test_quote_sets_target_and_allows_explicit_historical_comparison(self):
        old_id = it._save(it._directory('group-a'), block('blue')['image']['source']['bytes'])
        selection = it.select_message_images(reply(thumbnail='thumb'), 'group-a')
        images = it.fetch_message_images(selection, lambda att: block())
        selected = []
        async def invoke(content):
            image_id, _ = it.read_conversation_image('latest')
            selected.append(image_id)
            self.assertNotEqual(image_id, old_id)
            self.assertEqual(it.read_conversation_image(old_id)[0], old_id)
            return 'done'
        agent = AsyncMock()
        agent.messages = [{'role': 'user', 'content': [block('blue')]}]
        agent.invoke_async.side_effect = invoke
        await it.invoke_with_images(agent, 'question', images, None, 'group-a', selection)
        self.assertEqual(agent.messages[0]['content'], [block('blue')])
        agent.messages.append({'role': 'user', 'content': [block()]})
        await it.invoke_with_images(agent, 'continue', None, None, 'group-a', selection)
        self.assertIn('image', agent.messages[-1]['content'][0])
        self.assertEqual(selected[0], selected[1])

    async def test_failed_fetch_and_bad_upload_cannot_reuse_old_image(self):
        for payload in (None, {'image': {'source': {'bytes': b'bad'}}}):
            it._save(it._directory('group-a'), block()['image']['source']['bytes'])
            selection = it.select_message_images(original(), 'group-a')
            images = it.fetch_message_images(selection, lambda att: payload)
            agent = AsyncMock()
            def invoke(content):
                with self.assertRaises(ValueError):
                    it.read_conversation_image('latest')
                return 'done'
            agent.invoke_async.side_effect = invoke
            await it.invoke_with_images(agent, 'question', images, None, 'group-a')

    async def test_older_context_remains_available_without_claiming_a_new_upload(self):
        image_id = it._save(it._directory('group-a'), block()['image']['source']['bytes'])
        age = time.time() - 2 * 86400
        os.utime(it._directory('group-a') / f'{image_id}.png', (age, age))
        agent = AsyncMock()
        def invoke(text):
            self.assertIn('No new image is attached', text)
            self.assertIn('do not assume this image is the subject', text)
            self.assertEqual(it.read_conversation_image('latest')[0], image_id)
            self.assertEqual(it.read_conversation_image(image_id)[0], image_id)
            return 'done'
        agent.invoke_async.side_effect = invoke
        await it.invoke_with_images(agent, 'question', None, None, 'group-a')

    def test_direct_identification_does_not_lose_empty_selection(self):
        it._save(it._directory('group-a'), block()['image']['source']['bytes'])
        images = it.ImageBlocks(it.select_message_images(reply(), 'group-a'))
        with self.assertRaisesRegex(ValueError, 'No image is available'):
            it.identify_direct(lambda source: it.read_conversation_image(source), 'latest', images, None, 'group-a')
        self.assertIsNone(it._turn.get())

    def test_reply_context_preserves_current_command_and_quoted_caption(self):
        self.assertEqual(it.reply_context('current question', reply()['quote']),
                         '[replying to: quoted caption]\ncurrent question')


if __name__ == '__main__':
    unittest.main()
