"""Encounter hold: B replies inside A's tool; B's later slot still exists."""

from __future__ import annotations

from pathlib import Path

from playout.agents.actor import ActorAgent, ActorDeps, dispatch_action
from playout.canon import world_from_scenario
from playout.llm import LLM
from playout.loop import Simulation
from playout.models import SpeakAction, WaitAction, ActorDecision
from playout.schedule import build_day_plan
import random

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


def _together(world, a="mara", b="tomas", loc="quay"):
    world.set_actor_location(a, loc)
    world.set_actor_location(b, loc)


def test_speak_triggers_reply_before_return(tmp_path):
    world = world_from_scenario(tmp_path / "t.db", SCENARIO)
    _together(world)
    llm = LLM()
    assert llm.mode == "mock"
    deps = ActorDeps(world=world, llm=llm, actor_id="mara")
    result = dispatch_action(
        deps, SpeakAction(target="tomas", speech="舢板呢？你看見沒有。")
    )
    assert result.get("ok")
    assert result.get("encounter")
    events = list(world.all_events())
    speak = [e for e in events if e["kind"] == "speak" and e["actor_id"] == "mara"]
    assert speak
    after = [e for e in events if e["id"] > speak[-1]["id"] and e["actor_id"] == "tomas"]
    assert after, "Tomas should have acted before the speak tool returned"
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
            action=SpeakAction(target="tomas", speech="說話。"),
        )

    monkeypatch.setattr("playout.actors.decide", fake_decide)
    agent = ActorAgent(llm)
    result = agent.run(world, "mara")
    assert result.get("encounter")
    held = result["encounter"]["result"]
    assert held.get("action", {}).get("type") == "wait"
    world.close()


def test_b_move_ends_colocation(tmp_path, monkeypatch):
    from playout.models import MoveAction

    world = world_from_scenario(tmp_path / "t.db", SCENARIO)
    _together(world)
    llm = LLM()

    def fake_decide(w, _llm, actor_id, extra=""):
        if actor_id == "tomas":
            return ActorDecision(thought="走。", action=MoveAction(to="inn"))
        return ActorDecision(
            thought="問。",
            action=SpeakAction(target="tomas", speech="站住。"),
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
        return ActorDecision(
            thought="再說。",
            action=SpeakAction(target=other, speech="你聽好。"),
        )

    monkeypatch.setattr("playout.actors.decide", fake_decide)
    deps = ActorDeps(world=world, llm=llm, actor_id="mara", max_rounds=3, mutate_budget=4)
    for _ in range(4):
        dispatch_action(deps, SpeakAction(target="tomas", speech="聽我說。"))
    assert deps.encounter_rounds == 3
    assert deps.mutates_used == 4
    world.close()


def test_nested_run_cannot_open_encounter(tmp_path, monkeypatch):
    world = world_from_scenario(tmp_path / "t.db", SCENARIO)
    _together(world)
    llm = LLM()

    def fake_decide(w, _llm, actor_id, extra=""):
        other = "tomas" if actor_id == "mara" else "mara"
        return ActorDecision(
            thought="回。",
            action=SpeakAction(target=other, speech="嗯。"),
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
    dispatch_action(deps, SpeakAction(target="tomas", speech="舢板。"))
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
    # mara at quay with tomas: mock may speak or examine; either is a valid beat
    assert sim.world.day == 2 or tick.get("rolled_day")
    sim.world.close()
