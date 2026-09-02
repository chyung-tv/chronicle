"""Writer agent: consume-only chapter from the day's tape."""

from __future__ import annotations

from typing import Any

from playout.canon import World
from playout.llm import LLM
from playout.writer import write_day


class WriterAgent:
    def __init__(self, llm: LLM | None = None):
        self.llm = llm or LLM()

    def write(self, world: World, day: int) -> dict[str, Any]:
        return write_day(world, self.llm, day)
