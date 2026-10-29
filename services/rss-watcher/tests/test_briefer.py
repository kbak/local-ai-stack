"""Exercise newsbrief recovery without live models, feeds, or Signal messages."""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

os.environ.setdefault("BRIEFING_RECIPIENT", "+10000000000")
from rss_watcher import briefer
from stack_shared import llm_model


class NewsBriefTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.delays = []
        self.requests = []
        llm_model.invalidate_cache()
        self.addCleanup(llm_model.invalidate_cache)
        self.ready = httpx.Response(200, json={"running": [
            {"model": "example-7B", "state": "ready"},
            {"model": "example-coder-70B", "state": "ready"},
            {"model": "example-100B", "state": "starting"},
        ]}, request=httpx.Request("GET", "http://models.test/running"))
        for patcher in [
            patch.dict(os.environ, {"LLM_BASE_URL": "http://models.test/v1"}, clear=True),
            patch.object(llm_model, "time", SimpleNamespace(
                monotonic=lambda: self.now, sleep=self.sleep)),
            patch.object(briefer, "RSS_FEEDS", {"general": ["https://example.com/rss"]}),
            patch.object(briefer, "fetch_category", return_value=[{
                "source": "Example", "title": "News", "link": "https://example.com/news",
                "summary": "A news item.",
            }]),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def sleep(self, seconds):
        self.delays.append(seconds)
        self.now += seconds

    def test_transient_failures_recover_and_send_once(self):
        responses = iter([
            httpx.ReadTimeout("readiness request timed out"),
            httpx.Response(503, request=httpx.Request("GET", "http://models.test/running")),
            httpx.Response(200, json={"running": [
                {"model": "example-coder-70B", "state": "ready"},
                {"model": "example-100B", "state": "starting"},
            ]}, request=httpx.Request("GET", "http://models.test/running")),
            self.ready,
        ])

        def get(url, **kwargs):
            self.requests.append(url)
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return response

        with patch.object(llm_model.httpx, "get", side_effect=get), patch.object(
                briefer, "chat", return_value="Summary") as chat, patch.object(
                briefer, "send_brief") as send, self.assertLogs(llm_model.log, "WARNING") as logs:
            briefer.run_news_brief()

        self.assertEqual(self.delays, [1, 2, 4])
        self.assertEqual(self.requests, ["http://models.test/running"] * 4)
        self.assertTrue(any("ReadTimeout" in entry for entry in logs.output))
        self.assertTrue(any("HTTPStatusError" in entry for entry in logs.output))
        chat.assert_called_once()
        self.assertEqual(chat.call_args.kwargs["model"], "example-7B")
        send.assert_called_once_with("*RSS News Brief*\n\n*GENERAL*\nSummary", briefer.RSS_RECIPIENT)

    def test_persistent_failure_stops_without_sending(self):
        with patch.object(llm_model.httpx, "get", side_effect=httpx.ConnectTimeout("offline")), patch.object(
                briefer, "chat") as chat, patch.object(briefer, "send_brief") as send, self.assertLogs(
                llm_model.log, "WARNING"), self.assertRaisesRegex(RuntimeError, "readiness check failed"):
            briefer.run_news_brief()

        self.assertEqual(self.now, 120)
        self.assertGreater(len(self.delays), 1)
        chat.assert_not_called()
        send.assert_not_called()

    def test_delivery_failure_is_not_retried(self):
        with patch.object(llm_model.httpx, "get", return_value=self.ready), patch.object(
                briefer, "chat", return_value="Summary") as chat, patch.object(
                briefer, "send_brief", side_effect=httpx.ReadTimeout("delivery status unknown")) as send:
            with self.assertRaises(httpx.ReadTimeout):
                briefer.run_news_brief()

        chat.assert_called_once()
        send.assert_called_once()
        self.assertEqual(self.delays, [])

    def test_default_model_discovery_remains_fail_fast(self):
        with patch.object(llm_model.httpx, "get", side_effect=httpx.ConnectTimeout("offline")) as get:
            with self.assertLogs(llm_model.log, "WARNING"), self.assertRaises(RuntimeError):
                llm_model.resolve_model()
        get.assert_called_once()
        self.assertEqual(self.delays, [])


if __name__ == "__main__":
    unittest.main()
