from pathlib import Path
from types import SimpleNamespace

import pytest

from playout.agents.actor import ActorDeps, dispatch_action_async, prepare_move
from playout.agents.referee import apply_verdict
from playout.canon import world_from_scenario
from playout.llm import LLM
from playout.models import (
    MoveAction,
    MoveIntent,
    Patch,
    PerceptionOut,
    RefereeVerdict,
    SpeakAction,
    SpeechOut,
    StorytellerPlan,
)
from playout.movement import apply_move
from playout.referee import apply_action
from playout.storyteller import apply_patches

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


@pytest.fixture
def world(tmp_path):
    w = world_from_scenario(tmp_path / "t.db", SCENARIO)
    yield w
    w.close()


def test_quay_exits_exclude_cliff(world):
    ids = {e.id for e in world.exits("quay")}
    assert ids == {"bakery", "inn", "boathouse"}
    connected = {e.id for e in world.node("quay").connected}
    assert "cliff_path" not in connected
    assert "cliff_path" not in ids


def test_prepare_move_enum_from_quay(world):
    deps = ActorDeps(world=world, llm=LLM(), actor_id="tomas")
    ctx = SimpleNamespace(deps=deps)
    tool_def = SimpleNamespace(
        parameters_json_schema={"type": "object", "properties": {"to": {"type": "string"}}}
    )
    out = prepare_move(ctx, tool_def)
    assert out is not None
    enum = out.parameters_json_schema["properties"]["to"]["enum"]
    assert set(enum) == {"bakery", "inn", "boathouse"}
    assert "cliff_path" not in enum


def test_resolver_illegal_hop_stays_put(world):
    res = apply_move(world, MoveIntent(actor_id="tomas", to="cliff_path"))
    assert res.ok is False
    assert res.reason == "not_adjacent"
    assert world.actor("tomas")["location_id"] == "quay"
    ev = world.cx.execute(
        "SELECT kind, summary FROM events WHERE id=?", (res.event_id,)
    ).fetchone()
    assert ev["kind"] == "failed_move"
    assert "崖路" in ev["summary"] or "cliff_path" in ev["summary"] or "無法" in ev["summary"]
    percs = [p["text"] for p in world.perceptions_for("tomas", limit=5)]
    assert any("不相鄰" in t for t in percs)


def test_resolver_legal_hop_and_perceptions(world):
    res = apply_move(world, MoveIntent(actor_id="tomas", to="boathouse"))
    assert res.ok is True
    assert world.actor("tomas")["location_id"] == "boathouse"
    mara = [p["text"] for p in world.perceptions_for("mara", limit=8)]
    assert any("來了" in t for t in mara)
    self_p = [p["text"] for p in world.perceptions_for("tomas", limit=8)]
    assert any("船寮" in t for t in self_p)


def test_storyteller_cannot_teleport(world):
    apply_patches(
        world,
        StorytellerPlan(
            summary="有人想把張渡拽上崖。",
            patches=[
                Patch(op="move_actor", actor_id="tomas", location_id="cliff_path")
            ],
        ),
    )
    assert world.actor("tomas")["location_id"] == "quay"


def test_two_hops_one_beat_land_at_new_node(world):
    import asyncio

    async def go():
        deps = ActorDeps(world=world, llm=LLM(), actor_id="lena")
        r1 = await dispatch_action_async(deps, MoveAction(to="quay"))
        assert r1["ok"]
        assert world.actor("lena")["location_id"] == "quay"
        r2 = await dispatch_action_async(deps, MoveAction(to="boathouse"))
        assert r2["ok"]
        assert world.actor("lena")["location_id"] == "boathouse"
        assert deps.mutates_used == 2
        return r1, r2

    asyncio.run(go())
    # boathouse is not adjacent to bakery (start)
    assert "boathouse" not in {e.id for e in world.node("bakery").connected}


def test_speak_quotes_on_tape_and_perceptions(world):
    world.set_actor_location("mara", "quay")
    r = apply_action(
        world, "tomas", SpeakAction(target="mara", speech="舢板在我這兒。")
    )
    assert r["ok"]
    payload = world.event_payload(r["event_id"])
    assert payload["speeches"][0]["text"] == "舢板在我這兒。"
    ev = world.cx.execute(
        "SELECT summary FROM events WHERE id=?", (r["event_id"],)
    ).fetchone()
    assert "「舢板在我這兒。」" in ev["summary"]
    mara = " ".join(p["text"] for p in world.perceptions_for("mara", limit=6))
    assert "舢板在我這兒。" in mara


def test_apply_verdict_illegal_walk_does_not_claim_it(world):
    verdict = RefereeVerdict(
        summary="張渡走向崖路。",
        kind="move",
        patches=[
            Patch(op="move_actor", actor_id="tomas", location_id="cliff_path")
        ],
        perceptions=[
            PerceptionOut(actor_id="tomas", text="你到了崖路。"),
            PerceptionOut(actor_id="mara", text="你在船寮看見他走上崖。"),
        ],
    )
    out = apply_verdict(
        world,
        actor_id="tomas",
        counterpart_id=None,
        a_text="走向崖路",
        b_text=None,
        verdict=verdict,
    )
    assert world.actor("tomas")["location_id"] == "quay"
    ev = world.cx.execute(
        "SELECT kind, summary FROM events WHERE id=?", (out["event_id"],)
    ).fetchone()
    assert ev["kind"] == "failed_move"
    assert "走向崖路" not in ev["summary"]
    tomas = " ".join(p["text"] for p in world.perceptions_for("tomas", limit=8))
    assert "你到了崖路" not in tomas
    mara = " ".join(p["text"] for p in world.perceptions_for("mara", limit=8))
    assert "走上崖" not in mara


def test_apply_verdict_stores_quoted_speech_payload(world):
    world.set_actor_location("mara", "quay")
    verdict = RefereeVerdict(
        summary="張渡向關瑪打了個招呼。",
        kind="interact",
        speeches=[
            SpeechOut(speaker_id="tomas", hearer_id="mara", text="你也在。")
        ],
    )
    out = apply_verdict(
        world,
        actor_id="tomas",
        counterpart_id="mara",
        a_text="對關瑪道：你也在。",
        b_text=None,
        verdict=verdict,
    )
    payload = world.event_payload(out["event_id"])
    assert payload["speeches"][0]["text"] == "你也在。"
    ev = world.cx.execute(
        "SELECT kind, summary FROM events WHERE id=?", (out["event_id"],)
    ).fetchone()
    assert ev["kind"] == "speak"
    assert "「你也在。」" in ev["summary"]
