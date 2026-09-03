import os
import sys
import unittest
from pathlib import Path


os.environ.setdefault("PUBLIC_API_BEARER_KEY", "test-key-that-is-at-least-thirty-two-characters")
os.environ.setdefault(
    "PUBLIC_API_MODELS",
    "qwen3.8-27B-FP8,qwen3.6-35B-A3B-FP8",
)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import Settings, _is_openai_route, _is_v1_path, _model_from_request  # noqa: E402


class PolicyTests(unittest.TestCase):
    def test_path_gate(self) -> None:
        self.assertTrue(_is_v1_path("/v1/models"))
        self.assertFalse(_is_v1_path("/v1"))
        self.assertFalse(_is_v1_path("/metrics"))

    def test_only_selected_openai_routes_are_allowed(self) -> None:
        self.assertTrue(_is_openai_route("GET", "/v1/models", b"/v1/models"))
        self.assertTrue(
            _is_openai_route(
                "POST",
                "/v1/chat/completions",
                b"/v1/chat/completions",
            )
        )
        self.assertFalse(
            _is_openai_route(
                "POST",
                "/v1/load_lora_adapter",
                b"/v1/load_lora_adapter",
            )
        )
        self.assertFalse(
            _is_openai_route("POST", "/v1/../invocations", b"/v1/../invocations")
        )
        self.assertFalse(
            _is_openai_route("POST", "/v1/../metrics", b"/v1/%2e%2e/metrics")
        )

    def test_model_is_read_from_json_body(self) -> None:
        body = b'{"model":"qwen3.8-27B-FP8","messages":[]}'
        self.assertEqual(
            _model_from_request("/v1/chat/completions", None, body),
            "qwen3.8-27B-FP8",
        )
        self.assertIsNone(_model_from_request("/v1/chat/completions", None, b"not-json"))
        self.assertEqual(
            _model_from_request(
                "/v1/chat/completions",
                "qwen3.8-27B-FP8",
                b'{"model":"qwen-coder-7B"}',
            ),
            "qwen-coder-7B",
        )

    def test_runtime_settings_are_loopback_and_explicit(self) -> None:
        settings = Settings.from_environment()
        self.assertEqual(settings.upstream, "http://[::1]:8080")
        self.assertEqual(
            settings.models,
            frozenset({"qwen3.8-27B-FP8", "qwen3.6-35B-A3B-FP8"}),
        )


if __name__ == "__main__":
    unittest.main()
