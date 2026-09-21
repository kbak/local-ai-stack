"""Run with: python -m unittest discover -s signal-bot-patches -p 'test_*.py'."""
import asyncio
import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image

import image_tools as it


def png(color="red"):
    out = io.BytesIO()
    Image.new("RGBA", (32, 32), color).save(out, format="PNG")
    return out.getvalue()


class Signal:
    number = "+10000000000"
    base_url = "http://signal.test"

    def _resolve_group_id(self, recipient):
        return recipient


class ImageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = patch.object(it, "ROOT", Path(self.temp.name))
        self.root.start()
        self.addCleanup(self.root.stop)
        self.requests = []
        self.fail_delivery = False
        self.fail_backend = False

        def handler(request):
            self.requests.append(request)
            if request.url.path == "/v2/send":
                payload = json.loads(request.content)
                return httpx.Response(503 if self.fail_delivery and "base64_attachments" in payload else 201)
            if self.fail_backend:
                return httpx.Response(500)
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png("blue")).decode()}]})

        real_client = httpx.AsyncClient
        self.client = patch.object(it.httpx, "AsyncClient", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
        self.client.start()
        self.addCleanup(self.client.stop)
        self.env = patch.dict("os.environ", {"SIGNAL_IMAGE_BASE_URL": "http://image.test/v1"})
        self.env.start()
        self.addCleanup(self.env.stop)

    async def invoke(self, operation, recipient="chat-a", images=None):
        agent = AsyncMock()
        agent.invoke_async.side_effect = operation
        result = await it.invoke_with_images(agent, "user request", images, Signal(), recipient)
        self.assertIsNone(it._turn.get())
        return result

    async def test_generate_deliver_then_followup_edit(self):
        async def generate(_):
            return await it.run_image("Draw a blue square", "1024x1024")
        self.assertIn("successfully sent", await self.invoke(generate))
        generation = next(r for r in self.requests if r.url.path.endswith("generations"))
        self.assertEqual(json.loads(generation.content)["model"], "qwen-image-2.1")
        delivery = json.loads(self.requests[-1].content)
        self.assertEqual(delivery["recipients"], ["chat-a"])
        self.assertTrue(delivery["base64_attachments"][0].startswith("data:image/png;"))
        previous_id, previous = it._reference(it._directory("chat-a"), "latest")

        async def edit(text):
            self.assertIn(previous_id, text)
            return await it.run_image("Make it red", "1024x1024", "latest")
        self.assertIn("successfully sent", await self.invoke(edit))
        edit_request = next(r for r in self.requests if r.url.path.endswith("edits"))
        self.assertIn(b'name="image[]"', edit_request.content)
        self.assertIn(previous, edit_request.content)

    async def test_upload_becomes_reference_and_keeps_alpha(self):
        data = png((255, 0, 0, 0))
        async def edit(content):
            self.assertIn("Image references for this upload", content[0]["text"])
            _, saved = it._reference(it._directory("chat-a"), "latest")
            with Image.open(io.BytesIO(saved)) as im:
                self.assertEqual(im.getchannel("A").getextrema(), (0, 0))
            return await it.run_image("Make it blue", "1024x1024", "latest")
        await self.invoke(edit, images=[{"image": {"source": {"bytes": data}}}])

    async def test_cross_conversation_and_path_references_rejected(self):
        image_id = it._save(it._directory("chat-a"), png())
        async def edit(_):
            for ref in (image_id, "latest", "../../secret"):
                result = await it.run_image("edit", "1024x1024", ref)
                self.assertNotIn("successfully sent", result)
            return "done"
        await self.invoke(edit, recipient="chat-b")
        self.assertEqual(self.requests, [])

    async def test_bad_upload_does_not_edit_previous_image(self):
        it._save(it._directory("chat-a"), png())
        async def edit(_):
            return await it.run_image("edit", "1024x1024", "latest")
        result = await self.invoke(edit, images=[{"image": {"source": {"bytes": b"bad"}}}])
        self.assertIn("No image reference", result)
        self.assertEqual(self.requests, [])

    async def test_backend_and_delivery_failure_reported(self):
        async def generate(_):
            return await it.run_image("draw", "1024x1024")
        self.fail_backend = True
        self.assertIn("No image was sent", await self.invoke(generate))
        self.fail_backend = False
        self.fail_delivery = True
        self.assertIn("delivery failed", await self.invoke(generate))

    async def test_cancel_clears_context_and_sends_no_result(self):
        async def generate(_):
            raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.invoke(generate)
        self.assertIsNone(it._turn.get())
        self.assertEqual(self.requests, [])

    async def test_reference_retention_and_no_context(self):
        directory = it._directory("chat-a")
        for _ in range(it.KEEP_IMAGES + 2):
            it._save(directory, png())
        self.assertEqual(len(list(directory.glob("*.png"))), it.KEEP_IMAGES)
        self.assertIn("active Signal conversation", await it.run_image("draw", "1024x1024"))

    async def test_cancellation_during_backend_request(self):
        started = asyncio.Event()

        async def pending(request):
            started.set()
            await asyncio.Event().wait()

        # Leave progress/delivery intercepted; exercise cancellation of inference.
        self.client.stop()
        real_client = httpx.AsyncClient
        with patch.object(it, "_send", new_callable=AsyncMock) as send:
            with patch.object(it.httpx, "AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(pending), **kw)):
                async def generate(_):
                    return await it.run_image("draw", "1024x1024")
                task = asyncio.create_task(self.invoke(generate))
                await asyncio.wait_for(started.wait(), 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertEqual(send.await_count, 1)  # progress only
                self.assertEqual(list(it.ROOT.glob("*/*.png")), [])

    async def test_chat_model_selector_excludes_image_worker(self):
        from stack_shared.llm_model import _from_running, _DEFAULT_CODER_PATTERN
        ready = {"running": [{"model": "qwen-image-2.1", "state": "ready"}]}
        response = httpx.Response(200, json=ready, request=httpx.Request("GET", "http://models.test/running"))
        with patch("stack_shared.llm_model.httpx.get", return_value=response):
            self.assertIsNone(_from_running("http://models.test", _DEFAULT_CODER_PATTERN))


if __name__ == "__main__":
    unittest.main()
