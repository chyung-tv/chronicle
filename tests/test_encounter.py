"""Encounter hold: B replies inside A's interact; B's later slot still exists."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from playout.agents.actor import ActorAgent, ActorDeps, dispatch_action
from playout.canon import world_from_scenario
from playout.llm import LLM
from playout.loop import Simulation
from playout.models import (
    ActorDecision,
    ActorInner,
    InteractAction,
    RefereeVerdict,
    SpeechOut,
    WaitAction,
)
from playout.schedule import build_day_plan
import random

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


def _together(world, a="mara", b="tomas", loc="quay"):
    world.set_actor_location(a, loc)
    world.set_actor_location(b, loc)


def test_interact_triggers_reply_before_return(tmp_path):
    world = world_from_scenario(tmp_path / "t.db", SCENARIO)
    _together(world)
    llm = LLM()
    assert llm.mode == "mock"
    deps = ActorDeps(world=world, llm=llm, actor_id="mara")
    result = dispatch_action(
        deps, InteractAction(text="對張渡道：舢板呢？你看見沒有。")
    )
    assert result.get("ok")
    assert result.get("encounter")
    events = list(world.all_events())
    speak = [e for e in events if e["kind"] == "speak" and e["actor_id"] == "mara"]
    assert speak
    after = [e for e in events if e["id"] > speak[-1]["id"] and e["actor_id"] == "tomas"]
    assert after, "Tomas should have acted before the interact tool returned"
    world.close()


def test_b_wait_is_ignore(tmp_path, monkeypatch):
    world = world_from_scenario(tmp_path / "t.db", SCENARIO)
    _together(world)
    llm = LLM()

    def fake_decide(w, _llm, actor_id, extra=""):
        if actor_id == "tomas":
            return ActorDecision(thought="不理。", action=WaitAction())
        return ActorDecision(
            thought="問。",
            action=InteractAction(text="對張渡道：說話。"),
        )

    monkeypatch.setattr("playout.actors.decide", fake_decide)
    agent = ActorAgent(llm)
    result = agent.run(world, "mara")
    assert result.get("encounter")
    held = result["encounter"]["result"]
    assert held.get("action", {}).get("type") == "wait"
    world.close()


def test_b_move_ends_colocation(tmp_path, monkeypatch):
    world = world_from_scenario(tmp_path / "t.db", SCENARIO)
    _together(world)
    llm = LLM()

    def fake_decide(w, _llm, actor_id, extra=""):
        if actor_id == "tomas":
            return ActorDecision(
                thought="走。",
                action=InteractAction(text="前往鹹燈客棧（inn）"),
            )
        return ActorDecision(
            thought="問。",
            action=InteractAction(text="對張渡道：站住。"),
        )

    monkeypatch.setattr("playout.actors.decide", fake_decide)
    result = ActorAgent(llm).run(world, "mara")
    assert result.get("encounter")
    assert world.actor("tomas")["location_id"] == "inn"
    assert world.actor("mara")["location_id"] == "quay"
    world.close()


def test_max_rounds_stops_ping_pong(tmp_path, monkeypatch):
    world = world_from_scenario(tmp_path / "t.db", SCENARIO)
    _together(world)
    llm = LLM()

    def fake_decide(w, _llm, actor_id, extra=""):
        other = "tomas" if actor_id == "mara" else "mara"
        other_name = "張渡" if other == "tomas" else "關瑪"
        return ActorDecision(
            thought="再說。",
            action=InteractAction(text=f"對{other_name}道：你聽好。"),
        )

    monkeypatch.setattr("playout.actors.decide", fake_decide)
    deps = ActorDeps(world=world, llm=llm, actor_id="mara", max_rounds=3, mutate_budget=4)
    for _ in range(4):
        dispatch_action(deps, InteractAction(text="對張渡道：聽我說。"))
    assert deps.encounter_rounds == 3
    assert deps.mutates_used == 4
    world.close()


def test_nested_run_cannot_open_encounter(tmp_path, monkeypatch):
    world = world_from_scenario(tmp_path / "t.db", SCENARIO)
    _together(world)
    llm = LLM()

    def fake_decide(w, _llm, actor_id, extra=""):
        other = "tomas" if actor_id == "mara" else "mara"
        other_name = "張渡" if other == "tomas" else "關瑪"
        return ActorDecision(
            thought="回。",
            action=InteractAction(text=f"對{other_name}道：嗯。"),
        )

    monkeypatch.setattr("playout.actors.decide", fake_decide)
    result = ActorAgent(llm).run(
        world, "tomas", extra="有人剛對你說話", in_encounter=True, allow_encounter=False
    )
    assert not result.get("encounter")
    world.close()


def test_b_still_in_day_bag_after_encounter(tmp_path):
    world = world_from_scenario(tmp_path / "t.db", SCENARIO)
    _together(world)
    llm = LLM()
    deps = ActorDeps(world=world, llm=llm, actor_id="mara")
    dispatch_action(deps, InteractAction(text="對張渡道：舢板。"))
    plan = build_day_plan(world, [], random.Random(0))
    actors = [s["actor_id"] for s in plan["slots"] if s["kind"] == "actor"]
    assert "tomas" in actors
    assert "mara" in actors
    world.close()


def test_simulation_actor_slot_may_hold(tmp_path):
    sim = Simulation.create(str(tmp_path / "t.db"), SCENARIO)
    sim.world.set_actor_location("mara", "quay")
    sim.world.set_actor_location("tomas", "quay")
    sim.world.set_day_plan(
        {
            "day": 1,
            "length": 1,
            "cursor": 0,
            "steer": {"done": True, "intent_ids": []},
            "slots": [
                {"kind": "actor", "actor_id": "mara", "status": "pending"},
            ],
        }
    )
    tick = sim.tick()
    assert tick["ok"]
    assert sim.world.day == 2 or tick.get("rolled_day")
    sim.world.close()


def test_solo_take_via_interact(tmp_path):
    world = world_from_scenario(tmp_path / "t.db", SCENARIO)
    world.set_actor_location("lena", "bakery")
    llm = LLM()
    deps = ActorDeps(world=world, llm=llm, actor_id="lena")
    result = dispatch_action(
        deps, InteractAction(text="取走麵包舖菜刀（cleaver）")
    )
    assert result.get("ok")
    obj = world.object("cleaver")
    assert obj and obj["holder_id"] == "lena"
    kinds = [e["kind"] for e in world.all_events() if e["actor_id"] == "lena"]
    assert "take" in kinds
    world.close()


def test_live_nested_uses_await_run_not_run_sync(tmp_path, monkeypatch):
    world = world_from_scenario(tmp_path / "t.db", SCENARIO)
    _together(world)
    monkeypatch.setenv("PLAYOUT_LLM_MODE", "live")
    monkeypatch.setattr("playout.agents.actor.llm_mode", lambda: "live")
    monkeypatch.setattr("playout.agents.referee.llm_mode", lambda: "live")
    monkeypatch.setattr("playout.agents.actor.openrouter_model", lambda *_a, **_k: "fake")
    monkeypatch.setattr(
        "playout.agents.referee.openrouter_model", lambda *_a, **_k: "fake"
    )

    sync_calls: list[str] = []
    run_calls: list[str] = []

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            self.output_type = kwargs.get("output_type")
            self._tools: dict = {}

        def instructions(self, fn):
            return fn

        def tool(self, fn):
            self._tools[fn.__name__] = fn
            return fn

        async def run(self, prompt, deps=None):
            run_calls.append(getattr(self.output_type, "__name__", "") or "run")
            if self.output_type is RefereeVerdict:
                a_id = deps.actor_id if deps is not None else "mara"
                other = "tomas" if a_id == "mara" else "mara"
                # referee agent is constructed without deps; read from prompt
                return SimpleNamespace(
                    output=RefereeVerdict(
                        summary="關瑪問舢板，張渡答有船就走。",
                        kind="speak",
                        speeches=[
                            SpeechOut(
                                speaker_id="mara",
                                hearer_id="tomas",
                                text="舢板呢？你看見沒有。",
                            ),
                            SpeechOut(
                                speaker_id="tomas",
                                hearer_id="mara",
                                text="有船就走。",
                            ),
                        ],
                    )
                )
            ctx = SimpleNamespace(deps=deps)
            interact = self._tools["interact"]
            if deps.in_encounter:
                await interact(ctx, "有船就走。別那樣看我。")
            else:
                await interact(ctx, "對張渡道：舢板呢？你看見沒有。")
            return SimpleNamespace(output=ActorInner(thought="畢。"))

        def run_sync(self, *args, **kwargs):
            sync_calls.append("run_sync")
            raise AssertionError("Agent.run_sync must not be used")

    monkeypatch.setattr("playout.agents.actor.Agent", FakeAgent)
    monkeypatch.setattr("playout.agents.referee.Agent", FakeAgent)

    llm = LLM()
    llm.mode = "live"
    result = ActorAgent(llm).run(world, "mara")
    assert not sync_calls
    assert run_calls, "expected Agent.run for actor and referee"
    assert result.get("encounter") or result.get("ok")
    world.close()
