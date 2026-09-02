"""Event agent: the only writer of world patches."""

from __future__ import annotations

from typing import Any

from playout.agents.model import llm_mode, openrouter_model, strong_model_name
from playout.canon import World
from playout.llm import LLM
from playout.models import StorytellerPlan
from playout.storyteller import STORYTELLER_SYSTEM, apply_patches, inject_world_event


class EventAgent:
    def __init__(self, llm: LLM | None = None):
        self.llm = llm or LLM()

    def inject(self, world: World, text: str, *, kind: str = "world") -> dict[str, Any]:
        if self.llm.mode == "live" and llm_mode() == "live":
            plan = self._plan_live(world, text)
            if plan and plan.patches:
                eid = apply_patches(world, plan, kind=kind)
                world.set_meta("idle_scenes", "0")
                world.cx.commit()
                return {
                    "event_id": eid,
                    "summary": plan.summary,
                    "patches": [p.model_dump() for p in plan.patches],
                }
        return inject_world_event(world, self.llm, text, kind=kind)

    def apply_plan(
        self, world: World, plan: StorytellerPlan, *, kind: str = "world"
    ) -> dict[str, Any]:
        eid = apply_patches(world, plan, kind=kind)
        world.set_meta("idle_scenes", "0")
        world.cx.commit()
        return {
            "event_id": eid,
            "summary": plan.summary,
            "patches": [p.model_dump() for p in plan.patches],
        }

    def _plan_live(self, world: World, text: str) -> StorytellerPlan | None:
        from pydantic_ai import Agent

        actors = [
            {"id": a["id"], "name": a["name"], "location": a["location_id"]}
            for a in world.living_actors()
        ]
        locs = [
            {"id": l["id"], "name": l["name"]}
            for l in world.cx.execute("SELECT id, name FROM locations")
        ]
        user = f"事件：{text}\n人物：{actors}\n地點：{locs}\n天色：{world.meta('weather')}"
        agent: Agent[None, StorytellerPlan] = Agent(
            openrouter_model(strong_model_name()),
            output_type=StorytellerPlan,
            instructions=STORYTELLER_SYSTEM,
        )
        try:
            out = agent.run_sync(user)
            plan = out.output
            return plan if isinstance(plan, StorytellerPlan) else None
        except Exception:
            return None
