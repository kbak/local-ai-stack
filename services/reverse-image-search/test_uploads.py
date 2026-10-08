"""Exercise the real pinned MCP lifecycle and transport with large uploads."""
import base64
import unittest
from unittest.mock import patch

import httpx
import server


class UploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_twenty_mib_upload_through_real_mcp_and_oversized_rejection(self):
        app = server.create_app()
        headers = {'Accept': 'application/json, text/event-stream'}
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://image.test') as client:
                init = await client.post('/mcp/', headers=headers, json={
                    'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                    'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                               'clientInfo': {'name': 'upload-test', 'version': '1'}}})
                self.assertEqual(init.status_code, 200)
                headers['mcp-session-id'] = init.headers['mcp-session-id']
                encoded = base64.b64encode(b'x' * server.MAX_IMAGE_BYTES).decode()
                payload = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                           'params': {'name': 'reverse_image_search_upload',
                                      'arguments': {'image_base64': encoded, 'filename': 'image.png'}}}
                with patch.object(server, '_litterbox_upload', return_value='https://image.test/example.png') as upload, \
                     patch.object(server, '_saucenao', return_value=[]), \
                     patch.object(server, '_yandex', return_value={'search_url': 'https://search.test'}):
                    response = await client.post('/mcp/', headers=headers, json=payload)
                self.assertEqual(response.status_code, 200, response.text[:200])
                self.assertNotIn('"isError":true', response.text)
                self.assertIn('Reverse image search', response.text)
                self.assertEqual(len(upload.call_args.args[0]), server.MAX_IMAGE_BYTES)
                # Exercise the actual HTTP boundary without allocating another huge body.
                response = await client.post('/mcp/', headers={**headers,
                    'Content-Length': str(server.MAX_MCP_REQUEST_BYTES + 1)}, content=b'{}')
                self.assertEqual(response.status_code, 413)

    def test_decoded_limit_and_invalid_base64(self):
        with patch.object(server, 'MAX_IMAGE_BYTES', 8), patch.object(server, 'MAX_BASE64_BYTES', 12):
            self.assertEqual(server._decode_upload(base64.b64encode(b'x' * 8).decode(), 'image.png')[0], b'x' * 8)
            with self.assertRaisesRegex(ValueError, '20 MiB'):
                server._decode_upload(base64.b64encode(b'x' * 9).decode(), 'image.png')
            with self.assertRaisesRegex(ValueError, '20 MiB'):
                server._decode_upload('x' * 13, 'image.png')
            with self.assertRaisesRegex(ValueError, 'decode base64'):
                server._decode_upload('!!!!', 'image.png')


if __name__ == '__main__':
    unittest.main()
