"""Force heuristic mock LLM during pytest so a local OpenRouter key cannot call out."""

from __future__ import annotations

import os

os.environ["PLAYOUT_LLM_MODE"] = "mock"
