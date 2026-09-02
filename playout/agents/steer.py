"""Steer agent: campaigns only. Never writes World; EventAgent applies queued rungs."""

from __future__ import annotations

from typing import Any

from playout.canon import World
from playout.llm import LLM
from playout.steer import harvest_injections, mark_rung_injected, submit_intent


class SteerAgent:
    def __init__(self, llm: LLM | None = None):
        self.llm = llm or LLM()

    def submit(self, world: World, text: str) -> dict[str, Any]:
        return submit_intent(world, self.llm, text)

    def harvest(self, world: World) -> list[dict[str, Any]]:
        return harvest_injections(world)

    def mark_injected(self, world: World, intent_id: int, rung_id: str) -> None:
        mark_rung_injected(world, intent_id, rung_id)
