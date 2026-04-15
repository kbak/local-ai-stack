"""Thin wrapper for a single-turn LLM chat completion."""

from __future__ import annotations

from openai import OpenAI


def chat(
    system: str,
    user: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    temperature: float = 0.3,
) -> str:
    client = OpenAI(base_url=base_url, api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    return (response.choices[0].message.content or "").strip()
