"""Day-sequence simulation: steer at dawn, shuffled actor bag, random event slots."""

from __future__ import annotations

import asyncio
import random
import threading
from pathlib import Path
from typing import Any

from playout.agents.actor import ActorAgent
from playout.agents.event import EventAgent
from playout.agents.steer import SteerAgent
from playout.agents.writer import WriterAgent
from playout.canon import World, world_from_scenario, world_from_setup
from playout.llm import LLM
from playout.models import StorytellerPlan
from playout.schedule import (
    build_day_plan,
    insert_remaining_event,
    scheduled_steer_keys,
)

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"

CONFLICT_KINDS = {
    "attack",
    "kill",
    "attempted_kill",
    "speak",
    "examine",
    "interact",
    "steer_motive",
}


class Simulation:
    def __init__(
        self,
        world: World,
        llm: LLM | None = None,
        rng: random.Random | None = None,
    ):
        self.world = world
        self.llm = llm or LLM()
        self.rng = rng or random.Random()
        self.world.set_meta("llm_mode", self.llm.mode)
        self.world.set_meta("llm_model", self.llm.actor_model)
        self.world.cx.commit()
        self.actor_agent = ActorAgent(self.llm)
        self.event_agent = EventAgent(self.llm)
        self.steer_agent = SteerAgent(self.llm)
        self.writer_agent = WriterAgent(self.llm)
        self._lock = threading.RLock()
        self.reader = world.reader()

    def close(self) -> None:
        try:
            self.reader.close()
        except Exception:
            pass
        self.world.close()

    def _end_activity(self, error: str = "") -> None:
        self.world.set_activity("idle", error=error)

    def _run_locked(
        self,
        fn,
        *,
        activity: str,
        actor: str = "",
        detail: str = "",
        clear: bool = True,
    ) -> Any:
        with self._lock:
            err = ""
            try:
                self.world.set_activity(
                    activity, actor=actor, detail=detail, error=""
                )
                return fn()
            except Exception as e:
                err = str(e)[:500]
                raise
            finally:
                if clear:
                    self._end_activity(err)

    @classmethod
    def create(
        cls,
        db_path: str,
        scenario_path: str | None = None,
        *,
        database_url: str | None = None,
    ) -> "Simulation":
        world = world_from_scenario(
            db_path, scenario_path or SCENARIO, database_url=database_url
        )
        return cls(world)

    @classmethod
    def create_from_setup(
        cls,
        db_path: str,
        setup: dict[str, Any],
        *,
        database_url: str | None = None,
    ) -> "Simulation":
        world = world_from_setup(db_path, setup, database_url=database_url)
        return cls(world)

    @classmethod
    def open_existing(
        cls, db_path: str, *, database_url: str | None = None
    ) -> "Simulation":
        from playout import sql as dbsql

        if dbsql.is_postgres_source(db_path):
            if not dbsql.schema_exists(
                dbsql.story_id_from_source(db_path), url=database_url
            ):
                raise FileNotFoundError(db_path)
            return cls(World(db_path, database_url=database_url))
        path = Path(db_path)
        if not path.exists():
            raise FileNotFoundError(db_path)
        return cls(World(path, database_url=database_url))

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

    def _pressure_text(self) -> str:
        note = (self.world.meta("clock") or "").strip()
        if not note:
            return "鎮上的壓力還沒落地。"
        return f"局勢未歇：{note}"

    def _should_pressure(self) -> bool:
        brewing = self.world.cx.execute(
            "SELECT COUNT(*) c FROM steer_intents WHERE status IN ('brewing','attempted')"
        ).fetchone()["c"]
        if brewing:
            return False
        prev = self.world.day - 1
        if prev < 1:
            return False
        kinds = [e["kind"] for e in self.world.events_for_day(prev)]
        if any(k in CONFLICT_KINDS or str(k).startswith("steer_") for k in kinds):
            self.world.set_meta("idle_days", "0")
            self.world.cx.commit()
            return False
        idle = int(self.world.meta("idle_days", "0") or 0) + 1
        self.world.set_meta("idle_days", str(idle))
        self.world.cx.commit()
        return idle >= 1

    def _harvest_event_slots(self) -> list[dict[str, Any]]:
        injections: list[dict[str, Any]] = []
        plan = self.world.get_day_plan()
        already = scheduled_steer_keys(plan)
        for item in self.steer_agent.harvest(self.world):
            key = (item["intent_id"], item["rung_id"])
            if key in already:
                continue
            injections.append(
                {
                    "source": "steer",
                    "intent_id": item["intent_id"],
                    "rung_id": item["rung_id"],
                    "event_kind": f"steer_{item['kind']}",
                    "plan": item["plan"],
                }
            )
        return injections

    def _dawn(self) -> dict[str, Any]:
        injections = self._harvest_event_slots()
        if self._should_pressure():
            injections.append({"source": "pressure", "text": self._pressure_text()})
        plan = build_day_plan(self.world, injections, self.rng)
        self.world.set_day_plan(plan)
        return plan

    def ensure_plan(self) -> dict[str, Any]:
        plan = self.world.get_day_plan()
        if (
            plan
            and plan.get("day") == self.world.day
            and int(plan.get("cursor") or 0) < len(plan.get("slots") or [])
        ):
            return plan
        return self._dawn()

    def _run_event_slot(self, slot: dict[str, Any]) -> dict[str, Any]:
        if slot.get("source") == "steer" and slot.get("plan"):
            plan = StorytellerPlan.model_validate(slot["plan"])
            kind = slot.get("event_kind") or f"steer_{slot.get('rung_id', 'motive')}"
            out = self.event_agent.apply_plan(self.world, plan, kind=kind)
            if slot.get("intent_id") is not None and slot.get("rung_id"):
                self.steer_agent.mark_injected(
                    self.world, int(slot["intent_id"]), str(slot["rung_id"])
                )
            return out
        text = slot.get("text") or ""
        return self.event_agent.inject(self.world, text, kind="world")

    def _roll_day(self) -> dict[str, Any] | None:
        self.world.set_activity("writing", actor="writer", detail="章回正在寫成")
        day = self.world.day
        chapter = self.writer_agent.write(self.world, day)
        self.world.set_meta("day", str(day + 1))
        self.world.set_meta("scene", "0")
        self.world.set_day_plan(None)
        self.world.cx.commit()
        return chapter

    def tick(self, *, clear_activity: bool = True) -> dict[str, Any]:
        return self._run_locked(
            self._tick_unlocked,
            activity="thinking",
            detail="即將開演",
            clear=clear_activity,
        )

    def _tick_unlocked(self) -> dict[str, Any]:
        if not self.world.living_actors():
            return {"ok": False, "reason": "no living actors"}
        plan = self.ensure_plan()
        slots = plan.get("slots") or []
        cur = int(plan.get("cursor") or 0)
        if cur >= len(slots):
            chapter = self._roll_day()
            return {
                "ok": True,
                "rolled_day": True,
                "chapter": chapter,
                "time": {
                    "day": self.world.day,
                    "scene": 0,
                    "label": self.world.beat_label,
                },
            }
        slot = slots[cur]
        self.world.set_meta("scene", str(cur))
        self.world.cx.commit()
        result: dict[str, Any] | None = None
        if slot.get("kind") == "actor":
            aid = slot["actor_id"]
            name = self.world.actor(aid)["name"]
            self.world.set_activity(
                "thinking", actor=aid, detail=f"{name}正在抉擇"
            )
            result = asyncio.run(self.actor_agent.run_async(self.world, aid))
            slot["status"] = "done"
            if result.get("encounter"):
                slot["encounter"] = True
        else:
            self.world.set_activity(
                "injecting", actor="storyteller", detail="世變將至"
            )
            result = self._run_event_slot(slot)
            slot["status"] = "done"
        plan["cursor"] = cur + 1
        plan["slots"] = slots
        self.world.set_day_plan(plan)
        chapter = None
        rolled = False
        if plan["cursor"] >= len(plan["slots"]):
            chapter = self._roll_day()
            rolled = True
        return {
            "ok": True,
            "initiator": slot.get("actor_id"),
            "slot": slot,
            "result": result,
            "rolled_day": rolled,
            "chapter": chapter,
            "time": {
                "day": self.world.day if not rolled else self.world.day - 1,
                "scene": cur,
                "label": self.world.beat_label,
            },
        }

    def run_day(self) -> list[dict[str, Any]]:
        def go() -> list[dict[str, Any]]:
            logs: list[dict[str, Any]] = []
            start_day = self.world.day
            for _ in range(64):
                log = self.tick(clear_activity=False)
                logs.append(log)
                if not log.get("ok"):
                    break
                if self.world.day != start_day or log.get("rolled_day"):
                    break
            return logs

        return self._run_locked(
            go, activity="thinking", detail="演完今日", clear=True
        )

    def inject(self, text: str) -> dict[str, Any]:
        return self._run_locked(
            lambda: self.event_agent.inject(self.world, text),
            activity="injecting",
            actor="storyteller",
            detail="神諭注入中",
        )

    def steer(self, text: str) -> dict[str, Any]:
        def go() -> dict[str, Any]:
            out = self.steer_agent.submit(self.world, text)
            plan = self.world.get_day_plan()
            if plan and plan.get("day") == self.world.day:
                already = scheduled_steer_keys(plan)
                for item in self.steer_agent.harvest(self.world):
                    if item["intent_id"] != out.get("id"):
                        continue
                    key = (item["intent_id"], item["rung_id"])
                    if key in already:
                        continue
                    insert_remaining_event(
                        plan,
                        {
                            "source": "steer",
                            "intent_id": item["intent_id"],
                            "rung_id": item["rung_id"],
                            "event_kind": f"steer_{item['kind']}",
                            "plan": item["plan"],
                        },
                        self.rng,
                    )
                self.world.set_day_plan(plan)
            return out

        return self._run_locked(
            go, activity="steering", actor="steer", detail="導引醞釀中"
        )
