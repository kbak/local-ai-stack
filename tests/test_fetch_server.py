"""Readable fetch contracts, without network access or parser dependencies."""

import importlib.util
from pathlib import Path
import sys
import subprocess
from types import ModuleType
import unittest
from unittest.mock import AsyncMock, patch

from mcp.server.fastmcp.exceptions import ToolError


class FetchServerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        upstream = ModuleType("mcp_server_fetch.server")
        upstream.DEFAULT_USER_AGENT_AUTONOMOUS = "test-fetch-agent"
        upstream.check_may_autonomously_fetch_url = AsyncMock()
        upstream.fetch_url = AsyncMock(return_value=("Readable page", ""))
        self.upstream = upstream
        path = Path(__file__).resolve().parents[1] / "services/mcp-proxy/fetch-server.py"
        spec = importlib.util.spec_from_file_location("fetch_adapter_test", path)
        self.server = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"mcp_server_fetch.server": upstream}):
            spec.loader.exec_module(self.server)

    async def test_simplifies_html_and_checks_robots_before_fetching(self):
        result = await self.server.fetch("https://example.com/")
        self.assertEqual(result["content"], "Readable page")
        self.assertFalse(result["truncated"])
        self.assertNotIn("next_start_index", result)
        self.upstream.check_may_autonomously_fetch_url.assert_awaited_once_with(
            "https://example.com/", "test-fetch-agent")
        self.upstream.fetch_url.assert_awaited_once_with(
            "https://example.com/", "test-fetch-agent", force_raw=False)

    async def test_caps_large_requests_and_reports_truncation_without_a_retry_prompt(self):
        self.upstream.fetch_url.return_value = ("x" * 12000, "")
        result = await self.server.fetch("https://example.com/", max_length=1000000)
        self.assertEqual(len(result["content"]), 5000)
        self.assertEqual(result["next_start_index"], 5000)
        self.assertEqual(result["total_characters"], 12000)
        self.assertTrue(result["truncated"])
        self.assertNotIn("error", result)
        self.assertNotIn("Call the fetch", str(result))

    async def test_requested_excerpt_ends_without_suggesting_more_calls(self):
        self.upstream.fetch_url.return_value = ("first second", "")
        result = await self.server.fetch("https://example.com/", start_index=6)
        self.assertEqual(result["content"], "second")
        self.assertFalse(result["truncated"])
        result = await self.server.fetch("https://example.com/", start_index=100)
        self.assertEqual(result["content"], "")
        self.assertFalse(result["truncated"])

    async def test_robots_denial_prevents_page_request(self):
        self.upstream.check_may_autonomously_fetch_url.side_effect = ValueError("robots denied")
        with self.assertRaisesRegex(ValueError, "robots denied"):
            await self.server.fetch("https://example.com/")
        self.upstream.fetch_url.assert_not_awaited()

    async def test_parser_failure_does_not_expose_subprocess_commands_or_temp_paths(self):
        self.upstream.fetch_url.side_effect = subprocess.CalledProcessError(
            1, ["node", "ExtractArticle.js", "-i", "/tmp/internal.html"])
        with self.assertLogs("fetch_adapter_test", level="WARNING") as logs:
            result = await self.server.fetch("https://example.com/private?token=test-secret")
        self.assertFalse(result["retryable"])
        self.assertIn("Readable text could not be extracted", result["error"])
        self.assertNotIn("ExtractArticle", str(result))
        self.assertNotIn("/tmp/", str(result))
        self.assertEqual(logs.output, ["WARNING:fetch_adapter_test:HTML extraction failed (exit 1)"])

    async def test_schema_exposes_readable_http_fetch_without_raw_mode(self):
        tools = await self.server.mcp.list_tools()
        self.assertEqual([tool.name for tool in tools], ["fetch"])
        self.assertNotIn("raw", tools[0].inputSchema["properties"])
        for arguments in ({"url": "file:///tmp/private"},
                          {"url": "https://example.com", "start_index": -1},
                          {"url": "https://example.com", "max_length": 0}):
            with self.subTest(arguments=arguments), self.assertRaises(ToolError):
                await self.server.mcp.call_tool("fetch", arguments)
        self.upstream.fetch_url.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
