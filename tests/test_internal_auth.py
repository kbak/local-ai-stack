"""Authentication, child credential isolation, and non-destructive memory APIs."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

import httpx
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from stack_shared.auth_middleware import BearerAuthMiddleware
from stack_shared.mcp_client import proxy_auth_headers

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProxyAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_root_auth_covers_all_transports_and_path_variants(self):
        proxy = load('secure_proxy_test', 'services/mcp-proxy/secure_proxy.py')
        async def endpoint(request):
            return JSONResponse({'authorized': True})
        paths = ('/status', '/servers/demo/mcp', '/servers/demo/mcp/',
                 '/servers/demo/sse', '/servers/demo/messages/', '/unknown')
        app = proxy.authenticated_application('proxy-secret')(
            routes=[Route(path, endpoint, methods=['GET', 'POST', 'DELETE']) for path in paths])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://proxy') as client:
            for path in paths + ('/servers/demo/%6dcp', '//servers/demo/mcp'):
                for method in ('GET', 'POST', 'DELETE'):
                    for headers in ({}, {'Authorization': 'Bearer wrong'},
                                    [('Authorization', 'Bearer proxy-secret'), ('Authorization', 'Bearer wrong')]):
                        response = await client.request(method, path, headers=headers)
                        self.assertEqual(response.status_code, 401, (method, path))
            for path in paths:
                response = await client.get(path, headers={'Authorization': 'Bearer proxy-secret'})
                self.assertEqual(response.status_code, 200)

    def test_unconfigured_auth_fails_closed_before_start(self):
        proxy = load('secure_proxy_empty', 'services/mcp-proxy/secure_proxy.py')
        for token in ('', '  ', ' secret '):
            with self.assertRaises(ValueError):
                proxy.authenticated_application(token)

    def test_credentialed_workers_have_distinct_unprivileged_identities(self):
        proxy = load('secure_proxy_identities', 'services/mcp-proxy/secure_proxy.py')
        from mcp.client.stdio import StdioServerParameters
        servers = {name: StdioServerParameters(command='python', args=['tool.py'], env={})
                   for name in ('github', 'google-maps', 'browser', 'fetch')}
        proxy.isolate_servers(servers)
        uids = [server.args[1] for server in servers.values()]
        self.assertEqual(len(set(uids)), 4)
        self.assertNotIn('0', uids)
        for server in servers.values():
            self.assertEqual(server.args[0], '/opt/run_tool.py')
            self.assertEqual(server.env['HOME'], f'/home/tool-{server.args[1]}')
            self.assertEqual(server.env['UV_TOOL_DIR'], server.env['UV_CACHE_DIR'] + '/tools')
            self.assertEqual(server.env['XDG_CACHE_HOME'], f'/tmp/tool-cache-{server.args[1]}')

    async def test_credentials_reach_only_their_declared_stdio_child(self):
        proxy = load('secure_proxy_env', 'services/mcp-proxy/secure_proxy.py')
        script = '''from mcp.server.fastmcp import FastMCP
import os
mcp = FastMCP("environment-test")
@mcp.tool()
def inspect_environment() -> dict:
    return {key: os.getenv(key) for key in ("GITHUB_TOKEN", "GOOGLE_MAPS_API_KEY", "MCP_PROXY_AUTH_TOKEN", "CALDAV_PASSWORD", "MEMORY_API_TOKEN")}
mcp.run()
'''
        environment = {'GITHUB_TOKEN': 'github-only', 'GOOGLE_MAPS_API_KEY': 'maps-only',
                       'MCP_PROXY_AUTH_TOKEN': 'proxy-only', 'CALDAV_PASSWORD': 'private',
                       'MEMORY_API_TOKEN': 'memory-only'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'tool.py').write_text(script)
            (root / 'config.json').write_text(json.dumps({'mcpServers': {
                name: {'command': sys.executable, 'args': [str(root / 'tool.py')]}
                for name in ('github', 'google-maps', 'fetch')}}))
            with patch.dict(os.environ, environment):
                servers = proxy.load_servers(root / 'config.json', os.environ)
                for name, params in servers.items():
                    async with stdio_client(params) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            result = await session.call_tool('inspect_environment')
                            actual = json.loads(result.content[0].text)
                    expected = {key: None for key in environment}
                    if name == 'github':
                        expected['GITHUB_TOKEN'] = 'github-only'
                    if name == 'google-maps':
                        expected['GOOGLE_MAPS_API_KEY'] = 'maps-only'
                    self.assertEqual(actual, expected)


class CredentialRoutingTests(unittest.TestCase):
    def test_proxy_secret_is_not_sent_to_other_origins(self):
        with patch.dict(os.environ, {'MCP_PROXY_AUTH_TOKEN': 'private',
                                     'MCP_PROXY_URL': 'http://proxy.example:8083'}):
            self.assertEqual(proxy_auth_headers('http://proxy.example:8083/servers/time/mcp'),
                             {'Authorization': 'Bearer private'})
            for url in ('http://other.example:8083/mcp', 'https://proxy.example:8083/mcp',
                        'http://proxy.example:8090/mcp', 'http://proxy.example.evil:8083/mcp',
                        'http://proxy.example:8083@evil.example/mcp'):
                self.assertEqual(proxy_auth_headers(url), {}, url)


class MemoryAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        package = ModuleType('memory_test_app')
        package.__path__ = [str(ROOT / 'services/memory-mcp/app')]
        self.backend = ModuleType('memory_test_app.memory_backend')
        self.backend.is_ready = Mock(return_value=True)
        self.backend.pending_writes = Mock(return_value=0)
        self.backend.enqueue_add = Mock()
        self.backend.search = Mock(return_value=[{'memory': 'saved'}])
        self.backend.list_all = Mock(return_value=[{'memory': 'saved'}])
        self.modules = patch.dict(sys.modules, {'memory_test_app': package,
                                              'memory_test_app.memory_backend': self.backend})
        self.modules.start()
        self.env = patch.dict(os.environ, {'MEMORY_API_TOKEN': 'memory-secret'})
        self.env.start()
        self.server = load('memory_test_app.server', 'services/memory-mcp/app/server.py')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(self.server.app),
                                        base_url='http://localhost:8089')

    async def asyncTearDown(self):
        await self.client.aclose()
        self.env.stop()
        self.modules.stop()
        sys.modules.pop('memory_test_app.config', None)

    async def test_mcp_and_rest_require_auth_health_stays_available(self):
        self.assertEqual((await self.client.get('/health')).status_code, 200)
        for method, path in (('GET', '/v1/memory'), ('POST', '/v1/memory'),
                             ('GET', '/v1/memory/search?query=test'), ('POST', '/mcp/mcp'),
                             ('POST', '/health'), ('GET', '/health/')):
            self.assertEqual((await self.client.request(method, path)).status_code, 401)
        headers = {'Authorization': 'Bearer memory-secret'}
        result = await self.client.post('/v1/memory', headers=headers,
                                       json={'content': 'new fact', 'verbatim': True})
        self.assertEqual(result.status_code, 200)
        self.backend.enqueue_add.assert_called_once_with('new fact', user_id='default',
                                                         metadata=None, infer=False)
        self.assertEqual((await self.client.get('/v1/memory', headers=headers)).status_code, 200)
        self.assertEqual((await self.client.get('/v1/memory/search?query=test', headers=headers)).status_code, 200)

    async def test_no_rest_or_mcp_deletion_capability(self):
        for headers in ({}, {'Authorization': 'Bearer memory-secret'}):
            result = await self.client.delete('/v1/memory/example', headers=headers)
            self.assertIn(result.status_code, (401, 404, 405))
        tools = await self.server.mcp.list_tools()
        self.assertEqual({tool.name for tool in tools}, {'add_memory', 'search_memory', 'list_memories'})
        self.assertFalse(hasattr(self.server, 'delete_memory'))
        self.backend.enqueue_add.assert_not_called()

    def test_memory_without_a_token_does_not_start(self):
        with patch.object(self.server.config, 'API_TOKEN', ''):
            with self.assertRaisesRegex(RuntimeError, 'MEMORY_API_TOKEN'):
                load('memory_test_app.no_token', 'services/memory-mcp/app/server.py')


if __name__ == '__main__':
    unittest.main()
