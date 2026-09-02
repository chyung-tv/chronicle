"""OpenRouter via pydantic-ai, or mock when no key is set."""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "deepseek/deepseek-v4-flash-0731"


def api_key() -> str:
    return (
        os.getenv("PLAYOUT_LLM_API_KEY")
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )


def llm_mode() -> str:
    override = (os.getenv("PLAYOUT_LLM_MODE") or "").strip().lower()
    if override in ("mock", "live"):
        return override
    return "live" if api_key() else "mock"


def actor_model_name() -> str:
    return os.getenv("PLAYOUT_ACTOR_MODEL", DEFAULT_MODEL)


def strong_model_name() -> str:
    return os.getenv("PLAYOUT_STRONG_MODEL", DEFAULT_MODEL)


def openrouter_model(name: str | None = None) -> Any:
    from pydantic_ai.models.openrouter import OpenRouterModel
    from pydantic_ai.providers.openrouter import OpenRouterProvider

    return OpenRouterModel(
        name or actor_model_name(),
        provider=OpenRouterProvider(
            api_key=api_key(),
            app_url=os.getenv(
                "PLAYOUT_HTTP_REFERER", "https://github.com/chyung-tv/chronicle"
            ),
            app_title=os.getenv("PLAYOUT_APP_TITLE", "Play Out"),
        ),
    )
