"""Day-length bag: every actor ≥1, steer excluded, event index in 0..length."""

from __future__ import annotations

import random
from pathlib import Path

from playout.canon import world_from_scenario
from playout.loop import Simulation
from playout.schedule import build_day_plan, insert_event_slots, plan_actor_bag

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


def test_bag_length_and_coverage():
    ids = ["lena", "tomas", "mara", "ellis"]
    rng = random.Random(0)
    for _ in range(30):
        bag = plan_actor_bag(ids, rng, lo=4, hi=8)
        assert 4 <= len(bag) <= 8
        assert set(ids) <= set(bag)


def test_event_inserted_in_gaps():
    actor_slots = [
        {"kind": "actor", "actor_id": a, "status": "pending"}
        for a in ["lena", "tomas", "mara", "ellis"]
    ]
    rng = random.Random(1)
    injections = [{"source": "steer", "intent_id": 1, "rung_id": "motive"}]
    slots = insert_event_slots(actor_slots, injections, rng)
    assert len(slots) == 5
    event_idx = next(i for i, s in enumerate(slots) if s["kind"] == "event")
    assert 0 <= event_idx <= 4
    assert sum(1 for s in slots if s["kind"] == "actor") == 4


def test_build_plan_excludes_steer_from_length(tmp_path):
    world = world_from_scenario(tmp_path / "t.db", SCENARIO)
    rng = random.Random(2)
    injections = [
        {
            "source": "steer",
            "intent_id": 1,
            "rung_id": "motive",
            "plan": {"summary": "x", "patches": []},
        }
    ]
    plan = build_day_plan(world, injections, rng)
    n = len(world.living_actors())
    assert n <= plan["length"] <= 8
    actors = [s for s in plan["slots"] if s["kind"] == "actor"]
    events = [s for s in plan["slots"] if s["kind"] == "event"]
    assert len(actors) == plan["length"]
    assert len(events) == 1
    assert "steer" not in {s.get("actor_id") for s in actors}
    world.close()


def test_tick_walks_cursor_and_rolls_chapter(tmp_path):
    sim = Simulation.create(str(tmp_path / "t.db"), SCENARIO)
    sim.rng = random.Random(3)
    first = sim.tick()
    assert first["ok"]
    plan = sim.world.get_day_plan()
    assert plan is not None
    assert plan["cursor"] == 1
    logs = sim.run_day()
    # run_day continues remaining slots of the same day
    assert sim.world.day == 2
    chapters = sim.world.cx.execute("SELECT COUNT(*) c FROM chapters").fetchone()["c"]
    assert chapters == 1
    sim.world.close()


def test_seeded_plan_is_stable(tmp_path):
    world = world_from_scenario(tmp_path / "a.db", SCENARIO)
    p1 = build_day_plan(world, [], random.Random(42))
    p2 = build_day_plan(world, [], random.Random(42))
    assert [s["actor_id"] for s in p1["slots"]] == [s["actor_id"] for s in p2["slots"]]
    world.close()
