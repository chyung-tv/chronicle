"""Force heuristic mock LLM during pytest so a local OpenRouter key cannot call out."""

from __future__ import annotations

import os

os.environ["PLAYOUT_LLM_MODE"] = "mock"
os.environ["PLAYOUT_WORKER"] = "inline"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("PLAYOUT_DATABASE_URL", None)
