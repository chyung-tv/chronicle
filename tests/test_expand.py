from pathlib import Path

import pytest

from playout.agents.actor import ActorDeps, dispatch_action_async
from playout.agents.expand import ActorWriter, LocationWriter
from playout.agents.referee import apply_verdict
from playout.canon import world_from_scenario
from playout.llm import LLM
from playout.loop import Simulation
from playout.models import (
    MAX_LOCATIONS,
    MoveAction,
    MoveIntent,
    Patch,
    RefereeVerdict,
    StorytellerPlan,
)
from playout.movement import apply_move
from playout.referee import apply_action
from playout.storyteller import _heuristic_event, apply_patches

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


@pytest.fixture
def world(tmp_path):
    w = world_from_scenario(tmp_path / "t.db", SCENARIO)
    yield w
    w.close()


def test_add_location_and_edge_is_walkable(world):
    apply_patches(
        world,
        StorytellerPlan(
            summary="蘋果店開了。",
            patches=[
                Patch(
                    op="add_location",
                    location_id="apple_store",
                    name="蘋果店",
                    detail="玻璃門。",
                    connect_to="quay",
                )
            ],
        ),
    )
    loc = world.location("apple_store")
    assert loc["name"] == "蘋果店"
    assert loc["intact"]
    assert "apple_store" in {e.id for e in world.exits("quay")}
    res = apply_move(world, MoveIntent(actor_id="tomas", to="apple_store"))
    assert res.ok
    assert world.actor("tomas")["location_id"] == "apple_store"


def test_add_and_edit_actor(world):
    apply_patches(
        world,
        StorytellerPlan(
            summary="掌櫃來了。",
            patches=[
                Patch(
                    op="add_actor",
                    actor_id="clerk",
                    name="掌櫃",
                    location_id="quay",
                    voice="短句。",
                    want="把帳算清。",
                    constitution="精瘦。",
                ),
                Patch(
                    op="edit_actor",
                    actor_id="clerk",
                    condition="左臂受傷",
                    detail="左臂被繩勒傷。",
                ),
            ],
        ),
        kind="god_actor",
    )
    a = world.actor("clerk")
    assert a["alive"]
    assert a["location_id"] == "quay"
    assert a["injured"]
    assert "左臂" in (a["condition"] or "")
    apply_patches(
        world,
        StorytellerPlan(
            summary="掌櫃死了。",
            patches=[Patch(op="kill_actor", actor_id="clerk", detail="他倒下了。")],
        ),
    )
    assert not world.actor("clerk")["alive"]
    rows = list(world.cx.execute("SELECT id FROM actors WHERE id=?", ("clerk",)))
    assert rows


def test_describe_and_destroy_object(world):
    apply_patches(
        world,
        StorytellerPlan(
            summary="櫃上多一盒。",
            patches=[
                Patch(
                    op="add_object",
                    object_id="box",
                    name="木盒",
                    location_id="quay",
                    detail="未開。",
                ),
                Patch(op="describe_object", object_id="box", detail="蓋上有鹽。"),
            ],
        ),
    )
    obj = world.object("box")
    assert obj["description"] == "蓋上有鹽。"
    apply_patches(
        world,
        StorytellerPlan(
            summary="盒子毀了。",
            patches=[Patch(op="destroy_object", object_id="box")],
        ),
    )
    assert world.object("box")["destroyed"]


def test_disaster_without_named_place_does_not_hit_quay(world):
    plan = _heuristic_event(world, "隕石從天上來")
    ops = [p.op for p in plan.patches]
    assert "destroy_location" not in ops
    apply_patches(world, plan)
    assert world.location("quay")["intact"]


def test_disaster_named_place_destroys_it(world):
    plan = _heuristic_event(world, "碼頭倒塌了")
    assert any(
        p.op == "destroy_location" and p.location_id == "quay" for p in plan.patches
    )
    apply_patches(world, plan)
    assert not world.location("quay")["intact"]
    assert world.actor("tomas")["location_id"] != "quay" or not world.exits("quay")


def test_speech_does_not_spawn_location(world):
    from playout.models import SpeakAction

    world.set_actor_location("mara", "quay")
    n = world.location_count()
    apply_action(
        world, "tomas", SpeakAction(target="mara", speech="去蘋果店買東西。")
    )
    assert world.location_count() == n


def test_freeform_move_creates_place(world):
    n = world.location_count()
    r = apply_action(world, "tomas", MoveAction(to="蘋果店"))
    assert r["ok"]
    assert world.location_count() == n + 1
    dest = world.actor("tomas")["location_id"]
    assert dest != "quay"
    loc = world.location(dest)
    assert "蘋果" in loc["name"] or loc["id"].startswith("loc")
    assert dest in {e.id for e in world.exits("quay")}


def test_existing_non_adjacent_does_not_teleport(world):
    r = apply_action(world, "tomas", MoveAction(to="cliff_path"))
    assert r["ok"] is False
    assert world.actor("tomas")["location_id"] == "quay"


def test_vague_move_refuses(world):
    n = world.location_count()
    r = apply_action(world, "tomas", MoveAction(to="某處"))
    assert r["ok"] is False
    assert world.location_count() == n
    percs = " ".join(p["text"] for p in world.perceptions_for("tomas", limit=6))
    assert "沒有" in percs or r.get("reason") == "unknown_dest"


def test_location_cap_refuses_spawn(world):
    used = world.used_location_ids()
    # fill to cap
    i = 0
    while world.location_count() < MAX_LOCATIONS:
        i += 1
        lid = f"fill{i}"
        apply_patches(
            world,
            StorytellerPlan(
                summary="填。",
                patches=[
                    Patch(
                        op="add_location",
                        location_id=lid,
                        name=lid,
                        connect_to="quay",
                    )
                ],
            ),
        )
        used.add(lid)
    n = world.location_count()
    r = apply_action(world, "tomas", MoveAction(to="幽靈鋪"))
    assert r["ok"] is False
    assert world.location_count() == n


def test_referee_skips_spawn_and_destroy(world):
    n = world.location_count()
    apply_verdict(
        world,
        actor_id="tomas",
        counterpart_id=None,
        a_text="一拳打塌碼頭",
        b_text=None,
        verdict=RefereeVerdict(
            summary="碼頭還在。",
            kind="interact",
            patches=[
                Patch(op="destroy_location", location_id="quay", detail="不該發生"),
                Patch(
                    op="add_location",
                    location_id="nope",
                    name="不該有",
                    connect_to="quay",
                ),
            ],
        ),
    )
    assert world.location("quay")["intact"]
    assert world.location_count() == n


def test_god_insert_location_and_actor(world):
    loc = LocationWriter(LLM()).insert(world, "蘋果店")
    assert loc["ok"]
    assert world.find_location("蘋果店")
    act = ActorWriter(LLM()).insert(world, "掌櫃")
    assert act["ok"]
    assert world.find_actor("掌櫃")


def test_god_edit_actor_injury(world):
    out = ActorWriter(LLM()).insert(world, "張渡左臂受傷")
    assert out["ok"]
    a = world.actor("tomas")
    assert a["injured"]
    assert a["condition"]


def test_interact_finds_clerk(world):
    import asyncio

    from playout.models import InteractAction

    async def go():
        deps = ActorDeps(world=world, llm=LLM(), actor_id="tomas")
        return await dispatch_action_async(deps, InteractAction(text="找店員"))

    asyncio.run(go())
    assert world.find_actor("店員")


def test_simulation_insert_helpers(tmp_path):
    sim = Simulation.create(str(tmp_path / "s.db"), SCENARIO)
    try:
        sim.insert_location("側巷")
        assert sim.world.find_location("側巷")
        sim.insert_actor("路人甲")
        assert sim.world.find_actor("路人甲") or sim.world.actor_count() >= 4
    finally:
        sim.close()
