"""Live chat-routing + generation/edit smoke test, without sending Signal messages.

Run inside the built signal-bot container, with this script mounted under /checks.
Only image tools are registered: no messaging, memory or unrelated agent tools.
The real image backend is called, but delivery is captured under /tmp.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, "/app")

from strands import Agent
from strands.models.openai import OpenAIModel
from stack_shared.llm_model import resolve_model
import config
import image_tools


async def main():
    out = Path(tempfile.mkdtemp(prefix="signal-images-check-"))
    image_tools.ROOT = out / "references"
    deliveries = []

    async def capture(turn, message, data=None):
        if data:
            destination = out / f"result-{len(deliveries) + 1}.png"
            destination.write_bytes(data)
            deliveries.append(destination)
            print(f"Captured image: {destination}", flush=True)

    image_tools._send = capture
    skill_path = "/app/data/custom_skills/image_generation/image_generation.py"
    spec = importlib.util.spec_from_file_location("image_smoke_skill", skill_path)
    skill = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(skill)
    model_id = resolve_model(base_url=config.llm.base_url)
    print(f"Chat model: {model_id}", flush=True)
    model = OpenAIModel(
        client_args={"base_url": config.llm.base_url, "api_key": config.llm.api_key},
        model_id=model_id,
        params={"max_tokens": 2048, "temperature": 0.2,
                "extra_body": {"chat_template_kwargs": {"enable_thinking": True}}},
    )
    agent = Agent(model=model, tools=[skill.generate_image, skill.edit_image],
                  system_prompt="You are a Signal assistant. Use image tools to fulfill image generation and editing requests. Use supplied reference IDs for edits. Images are sent by the tools. Keep replies brief.",
                  callback_handler=None)
    for i, prompt in enumerate([
        "Create an image of a red ceramic robot holding a white sign reading HELLO, on a plain grey background.",
        "Make that robot blue, keeping the same composition and HELLO sign.",
    ], 1):
        result = await asyncio.wait_for(image_tools.invoke_with_images(agent, prompt, None, object(), "test-conversation"), 360)
        print(f"Turn {i}: {result}", flush=True)
        assert len(deliveries) == i, f"Expected exactly {i} generated images"
    calls = [block["toolUse"]["name"] for msg in agent.messages for block in msg.get("content", []) if "toolUse" in block]
    assert calls == ["generate_image", "edit_image"], calls
    print(json.dumps({"tools": calls, "artifacts": [str(p) for p in deliveries]}), flush=True)


asyncio.run(main())
