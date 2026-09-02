"""OpenAI-compatible client with a heuristic mock when no key is set."""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()


def extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("no json in llm output")


class LLM:
    def __init__(self) -> None:
        self.api_key = os.getenv("PLAYOUT_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        self.base_url = os.getenv("PLAYOUT_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.actor_model = os.getenv("PLAYOUT_ACTOR_MODEL", "gpt-4o-mini")
        self.strong_model = os.getenv("PLAYOUT_STRONG_MODEL", "gpt-4o")
        self.mode = "live" if self.api_key else "mock"

    def complete(self, system: str, user: str, *, strong: bool = False, temperature: float = 0.7) -> str:
        if self.mode == "mock":
            return ""
        model = self.strong_model if strong else self.actor_model
        r = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=90.0,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def complete_json(self, system: str, user: str, *, strong: bool = False) -> dict[str, Any]:
        raw = self.complete(system, user, strong=strong)
        if not raw:
            return {}
        try:
            return extract_json(raw)
        except Exception:
            raw2 = self.complete(system, user + "\n\nReturn ONLY JSON.", strong=strong, temperature=0.2)
            return extract_json(raw2)
