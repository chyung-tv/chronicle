"""Scene-based simulation loop."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from playout.actors import actor_turn
from playout.canon import World, world_from_scenario
from playout.llm import LLM
from playout.steer import submit_intent, tick_intents
from playout.storyteller import inject_world_event
from playout.writer import write_day

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


class Simulation:
    def __init__(self, world: World, llm: LLM | None = None):
        self.world = world
        self.llm = llm or LLM()
        self.world.set_meta("llm_mode", self.llm.mode)
        self.world.set_meta("llm_model", self.llm.actor_model)
        self._rr = 0
        self._lock = threading.RLock()

    @classmethod
    def create(cls, db_path: str, scenario_path: str | None = None) -> "Simulation":
        world = world_from_scenario(db_path, scenario_path or SCENARIO)
        return cls(world)

    @classmethod
    def open(cls, db_path: str, scenario_path: str | None = None) -> "Simulation":
        path = Path(db_path)
        scenario = scenario_path or SCENARIO
        if path.exists():
            world = World(path)
            if world.meta("title"):
                return cls(world)
            world.close()
        return cls.create(str(path), scenario)

    def _next_initiator(self) -> str | None:
        living = self.world.living_actors()
        if not living:
            return None
        actor = living[self._rr % len(living)]
        self._rr += 1
        return actor["id"]

    def _auto_pressure(self) -> dict | None:
        idle = int(self.world.meta("idle_scenes", "0") or 0)
        brewing = self.world.cx.execute(
            "SELECT COUNT(*) c FROM steer_intents WHERE status IN ('brewing','attempted')"
        ).fetchone()["c"]
        if brewing:
            return None
        kinds = [
            r["kind"]
            for r in self.world.cx.execute(
                "SELECT kind FROM events WHERE day=? AND scene=?",
                (self.world.day, self.world.scene),
            )
        ]
        conflict = any(
            k in kinds
            for k in (
                "attack",
                "kill",
                "attempted_kill",
                "speak",
                "examine",
                "steer_motive",
            )
        )
        if conflict:
            self.world.set_meta("idle_scenes", "0")
            return None
        idle += 1
        self.world.set_meta("idle_scenes", str(idle))
        if idle < 3:
            return None
        clock = self.world.meta("clock") or ""
        return inject_world_event(
            self.world,
            self.llm,
            f"The incoming storm reminds the town: {clock}. Thunder over the cliff path. Nobody can pretend the skiff will wait.",
            kind="world",
        )

    def tick(self) -> dict[str, Any]:
        """One scene: one initiator, optional reaction, then steer."""
        with self._lock:
            return self._tick_unlocked()

    def _tick_unlocked(self) -> dict[str, Any]:
        initiator = self._next_initiator()
        if not initiator:
            return {"ok": False, "reason": "no living actors"}
        result = actor_turn(self.world, self.llm, initiator)
        reaction = None
        if result.get("expect_reaction"):
            target = result["expect_reaction"]
            t = self.world.actor(target)
            if (
                t["alive"]
                and t["location_id"] == self.world.actor(initiator)["location_id"]
            ):
                reaction = actor_turn(
                    self.world,
                    self.llm,
                    target,
                    extra="You were just spoken to or attacked. React. You may speak, attack, wait, or leave.",
                )
        pressure = self._auto_pressure()
        steer = tick_intents(self.world)
        rolled = self.world.advance_scene()
        chapter = None
        if rolled["rolled_day"]:
            chapter = write_day(self.world, self.llm, rolled["previous_day"])
        return {
            "ok": True,
            "initiator": initiator,
            "result": result,
            "reaction": reaction,
            "steer": steer,
            "pressure": pressure,
            "time": {
                "day": self.world.day,
                "scene": self.world.scene,
                "label": self.world.time_label,
            },
            "chapter": chapter,
        }

    def run_day(self) -> list[dict[str, Any]]:
        logs = []
        start_day = self.world.day
        # scenes remaining this day including wrapping
        for _ in range(self.world.scenes_per_day):
            logs.append(self.tick())
            if self.world.day != start_day:
                break
        return logs

    def inject(self, text: str) -> dict[str, Any]:
        with self._lock:
            return inject_world_event(self.world, self.llm, text)

    def steer(self, text: str) -> dict[str, Any]:
        with self._lock:
            return submit_intent(self.world, self.llm, text)
