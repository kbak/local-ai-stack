"""Deployment configuration contracts; no service dependencies or GPU required."""

import importlib.util
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AudioDeviceTests(unittest.TestCase):
    def validate(self, selection="GPU-selected", count=1, actual="Test GPU", expected=""):
        package = ModuleType("app")
        package.config = SimpleNamespace(EXPECTED_AUDIO_GPU=expected)
        cuda = SimpleNamespace(device_count=lambda: count, get_device_name=lambda _: actual)
        with patch.dict(sys.modules, {"app": package, "torch": SimpleNamespace(cuda=cuda)}):
            module = load("app.inference", "services/audio-api/app/inference.py")
            with patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": selection}):
                module.validate_audio_gpu()

    def test_single_selected_device_without_name_constraint(self):
        self.validate(actual="Any supported device")

    def test_explicit_name_constraint(self):
        self.validate(expected="Test GPU")
        with self.assertRaisesRegex(RuntimeError, "Audio GPU must"):
            self.validate(expected="Other device")

    def test_isolation_still_required(self):
        with self.assertRaisesRegex(RuntimeError, "explicit CUDA_VISIBLE_DEVICES"):
            self.validate(selection="")
        for count in (0, 2):
            with self.subTest(count=count), self.assertRaisesRegex(RuntimeError, "Exactly one"):
                self.validate(count=count)


class MemoryConfigurationTests(unittest.TestCase):
    def test_proxy_allowlist_is_explicit_and_whitespace_is_trimmed(self):
        with patch.dict(os.environ, {
            "MEMORY_ALLOWED_HOSTS": " memory.example.com, memory.internal:8089, ",
            "MEMORY_ALLOWED_ORIGINS": " https://memory.example.com, ",
        }):
            config = load("memory_config", "services/memory-mcp/app/config.py")
        self.assertEqual(config.ALLOWED_HOSTS, ["memory.example.com", "memory.internal:8089"])
        self.assertEqual(config.ALLOWED_ORIGINS, ["https://memory.example.com"])

    def test_defaults_do_not_allow_arbitrary_hosts(self):
        with patch.dict(os.environ, {}, clear=True):
            config = load("memory_config", "services/memory-mcp/app/config.py")
        self.assertIn("localhost:*", config.ALLOWED_HOSTS)
        self.assertNotIn("*", config.ALLOWED_HOSTS)
        self.assertNotIn("*", config.ALLOWED_ORIGINS)


class SystemdTemplateTests(unittest.TestCase):
    def test_all_templates_render_for_a_custom_checkout(self):
        renderer = load("render_systemd", "scripts/render-systemd.py")
        root = Path('/opt/AI Stack/100% ready')
        for template in (ROOT / "config/systemd").glob("*.service"):
            with self.subTest(template=template.name):
                rendered = renderer.render(template.read_text(), root)
                self.assertNotIn("@STACK_ROOT@", rendered)
                self.assertIn('"/opt/AI Stack/100%% ready/', rendered)

    def test_rejects_newline_in_installation_path(self):
        renderer = load("render_systemd", "scripts/render-systemd.py")
        with self.assertRaises(ValueError):
            renderer.render("@STACK_ROOT@", Path("/tmp/path\nextra"))


class SearchTemplateTests(unittest.TestCase):
    def render(self, secret):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = 'secret: "__SEARXNG_SECRET__"\nkey: "__BRAVE_SEARCH_API_KEY__"\n'
            (root / "template.yml").write_text(source)
            script = (ROOT / "docker/searxng/entrypoint.sh").read_text()
            script = script.replace("/etc/searxng/settings.template.yml", str(root / "template.yml"))
            script = script.replace("/etc/searxng/settings.yml", str(root / "settings.yml"))
            script = script.replace("exec /usr/local/searxng/entrypoint.sh", "exit 0")
            result = subprocess.run(["sh", "-c", script], capture_output=True, text=True,
                                    env={"PATH": os.defpath, "BRAVE_SEARCH_API_KEY": "test-key",
                                         "SEARXNG_SECRET": secret})
            output = root / "settings.yml"
            return result.returncode, output.read_text() if output.exists() else ""

    def test_renders_local_credentials(self):
        code, output = self.render("test-secret")
        self.assertEqual(code, 0)
        self.assertEqual(output, 'secret: "test-secret"\nkey: "test-key"\n')

    def test_rejects_empty_or_unsafe_secret(self):
        for secret in ("", "quote\"break", "amp&break", "line\nbreak"):
            with self.subTest(secret=secret):
                code, _ = self.render(secret)
                self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
