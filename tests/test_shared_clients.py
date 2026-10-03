"""Offline contracts for the clients shared by watchers, bot, and voice skills."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'shared'), str(ROOT / 'services/signal-bot/skills')]

from stack_shared import llm_chat, mcp_client
from _shared import llm as bot_llm

SKILLS = {
    'arxiv/arxiv_skill': (20, 'arxiv'),
    'currency/currency_skill': (15, 'currency'),
    'finance/finance_skill': (15, 'finance'),
    'time/time_skill': (15, 'time'),
    'weather/weather_skill': (15, 'weather'),
    'google_maps/maps': (15, 'google-maps'),
    'pdf/pdf_skill': (120, None),
}


def load_skill(name):
    path = ROOT / 'services/signal-bot/skills' / f'{name}.py'
    spec = importlib.util.spec_from_file_location(f'test_skills.{name.replace("/", ".")}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MCPContracts(unittest.TestCase):
    def test_skills_load_without_the_custom_skills_directory_on_sys_path(self):
        # The bot registry loads each entry point by file path, before other
        # skills happen to make their parent directory importable.
        script = """
import importlib.util
from pathlib import Path
import sys
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'shared'))
for name in sys.argv[2:]:
    path = root / 'services/signal-bot/skills' / (name + '.py')
    spec = importlib.util.spec_from_file_location('custom_skills.' + name.replace('/', '.'), path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
"""
        result = subprocess.run(
            [sys.executable, '-I', '-c', script, str(ROOT), *SKILLS],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def setUp(self):
        self.requests = []
        self.payload = {'result': {'content': [
            {'type': 'text', 'text': 'first'},
            {'type': 'image', 'data': 'ignored'},
            {'type': 'text', 'text': 'second'},
        ]}}
        self.session = 'test-session'
        self.status = 200
        self.sse = False
        self.client_type = httpx.Client
        self.patcher = patch.object(mcp_client.httpx, 'Client', side_effect=self.make_client)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def make_client(self, **kwargs):
        return self.client_type(transport=httpx.MockTransport(self.handle), **kwargs)

    def handle(self, request):
        body = json.loads(request.content)
        self.requests.append((request, body))
        if body['method'] == 'initialize':
            headers = {'mcp-session-id': self.session} if self.session else {}
            return httpx.Response(200, headers=headers, json={'result': {}})
        if body['method'] == 'notifications/initialized':
            return httpx.Response(202)
        if self.sse:
            return httpx.Response(self.status, text=f'event: message\ndata: {json.dumps(self.payload)}\n\n')
        return httpx.Response(self.status, json=self.payload)

    def test_skill_wire_contracts(self):
        for name, (timeout, server) in SKILLS.items():
            with self.subTest(skill=name):
                self.requests.clear()
                self.sse = server is None
                module = load_skill(name)
                self.assertEqual(module._call_mcp('lookup', {'query': 'test'}), 'first\nsecond')
                methods = [body['method'] for _, body in self.requests]
                expected = ['initialize', 'tools/call']
                if self.sse:
                    expected.insert(1, 'notifications/initialized')
                self.assertEqual(methods, expected)
                url = f'http://mcp-proxy:8083/servers/{server}/mcp' if server else 'http://pdf-inspector:8085/mcp/'
                accept = 'application/json, text/event-stream' if self.sse else 'application/json'
                for i, (request, body) in enumerate(self.requests):
                    self.assertEqual(str(request.url), url)
                    self.assertEqual(request.method, 'POST')
                    self.assertEqual(request.headers['accept'], accept)
                    self.assertEqual(request.headers['content-type'], 'application/json')
                    self.assertEqual(request.extensions['timeout']['read'], timeout)
                    self.assertEqual(body['jsonrpc'], '2.0')
                    if i:
                        self.assertEqual(request.headers['mcp-session-id'], self.session)
                    else:
                        self.assertNotIn('mcp-session-id', request.headers)
                self.assertEqual(self.requests[0][1], {
                    'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                    'params': {'protocolVersion': '2024-11-05', 'capabilities': {},
                               'clientInfo': {'name': 'signal-bot', 'version': '1.0'}},
                })
                self.assertEqual(self.requests[-1][1], {
                    'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                    'params': {'name': 'lookup', 'arguments': {'query': 'test'}},
                })

    def test_service_auth_and_defaults(self):
        self.assertEqual(mcp_client.call_mcp('http://mcp.test/mcp', 'lookup', {}, auth_token='test-token'), 'first\nsecond')
        self.assertEqual(len(self.requests), 2)
        for request, _ in self.requests:
            self.assertEqual(request.headers['authorization'], 'Bearer test-token')
            self.assertEqual(request.headers['accept'], 'application/json, text/event-stream')
            self.assertEqual(request.extensions['timeout']['read'], 20)
        self.assertEqual(self.requests[0][1]['params']['clientInfo']['name'], 'stack-service')

    def test_service_accepts_sse(self):
        self.sse = True
        self.assertEqual(mcp_client.call_mcp('http://mcp.test/mcp', 'lookup', {}), 'first\nsecond')

    def test_missing_session_stops_before_tool(self):
        self.session = None
        with self.assertRaisesRegex(RuntimeError, 'No mcp-session-id returned during initialize'):
            mcp_client.call_mcp('http://mcp.test/mcp', 'lookup', {})
        self.assertEqual(len(self.requests), 1)
        for name in SKILLS:
            with self.subTest(skill=name):
                with self.assertRaisesRegex(RuntimeError, '^No session ID returned$'):
                    load_skill(name)._call_mcp('lookup', {})

    def test_rpc_error_messages(self):
        self.payload = {'error': {'message': 'denied'}}
        with self.assertRaisesRegex(RuntimeError, '^MCP error: denied$'):
            mcp_client.call_mcp('http://mcp.test/mcp', 'lookup', {})
        for name in SKILLS:
            with self.subTest(skill=name):
                with self.assertRaisesRegex(RuntimeError, '^denied$'):
                    load_skill(name)._call_mcp('lookup', {})

    def test_only_maps_raises_on_tool_error(self):
        self.payload = {'result': {'isError': True, 'content': [{'type': 'text', 'text': 'not found'}]}}
        for name in SKILLS:
            with self.subTest(skill=name):
                call = load_skill(name)._call_mcp
                if name == 'google_maps/maps':
                    with self.assertRaisesRegex(RuntimeError, '^not found$'):
                        call('lookup', {})
                else:
                    self.assertEqual(call('lookup', {}), 'not found')
        self.assertEqual(mcp_client.call_mcp('http://mcp.test/mcp', 'lookup', {}), 'not found')

    def test_empty_maps_error(self):
        self.payload = {'result': {'isError': True}}
        with self.assertRaisesRegex(RuntimeError, '^MCP tool lookup failed$'):
            load_skill('google_maps/maps')._call_mcp('lookup', {})

    def test_http_errors_propagate(self):
        self.status = 503
        with self.assertRaises(httpx.HTTPStatusError):
            load_skill('pdf/pdf_skill')._call_mcp('lookup', {})


class ChatContracts(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.create = self.client.chat.completions.create
        self.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='<think>private\nreasoning</think> answer '))])
        client_patch = patch.object(llm_chat, 'get_client', return_value=self.client)
        self.get_client = client_patch.start()
        self.addCleanup(client_patch.stop)
        config_patch = patch.dict(sys.modules, {'config': SimpleNamespace(llm=SimpleNamespace(
            base_url='http://models.test/v1', api_key='test-key', model_id='fallback'))})
        config_patch.start()
        self.addCleanup(config_patch.stop)

    def test_service_defaults_and_reasoning(self):
        with patch.object(llm_chat, 'resolve_model', return_value='loaded') as resolve:
            self.assertEqual(llm_chat.chat('system', 'user'), 'answer')
            resolve.assert_called_once_with(base_url=None)
        self.assertEqual(self.create.call_args.kwargs, {
            'model': 'loaded', 'messages': [{'role': 'system', 'content': 'system'},
                                           {'role': 'user', 'content': 'user'}],
            'temperature': 0.3,
            'extra_body': {'chat_template_kwargs': {'enable_thinking': False}},
        })

    def test_bot_defaults_use_loaded_model(self):
        with patch('stack_shared.llm_model.resolve_model', return_value='loaded') as resolve:
            self.assertEqual(bot_llm.chat('system', 'user'), 'answer')
            resolve.assert_called_once_with(base_url='http://models.test/v1')
        self.get_client.assert_called_once_with(base_url='http://models.test/v1', api_key='test-key')
        kwargs = self.create.call_args.kwargs
        self.assertEqual(kwargs['model'], 'loaded')
        self.assertEqual(kwargs['max_tokens'], 128)
        self.assertEqual(kwargs['temperature'], 0.0)
        self.assertEqual(kwargs['extra_body'], {'chat_template_kwargs': {'enable_thinking': False}})

    def test_bot_resolution_failure_uses_configured_fallback(self):
        with patch('stack_shared.llm_model.resolve_model', side_effect=RuntimeError('unavailable')):
            with self.assertLogs(bot_llm.logger, level='WARNING'):
                self.assertEqual(bot_llm.chat('s', 'u', max_tokens=24, temperature=0.2), 'answer')
        kwargs = self.create.call_args.kwargs
        self.assertEqual((kwargs['model'], kwargs['max_tokens'], kwargs['temperature']), ('fallback', 24, 0.2))

    def test_bot_request_failure_returns_none_but_service_propagates(self):
        self.create.side_effect = RuntimeError('unavailable')
        with patch('stack_shared.llm_model.resolve_model', return_value='loaded'):
            with self.assertLogs(bot_llm.logger, level='ERROR'):
                self.assertIsNone(bot_llm.chat('s', 'u'))
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            llm_chat.chat('s', 'u', model='loaded')

    def test_empty_completion(self):
        self.create.return_value.choices[0].message.content = None
        self.assertEqual(llm_chat.chat('s', 'u', model='loaded'), '')


if __name__ == '__main__':
    unittest.main()
