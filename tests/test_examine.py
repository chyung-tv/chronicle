from pathlib import Path
from types import SimpleNamespace

import pytest

from playout.agents.actor import ActorDeps, dispatch_action, prepare_examine
from playout.canon import world_from_scenario
from playout.examine import apply_examine, examine_aims
from playout.llm import LLM
from playout.models import (
    ExamineAction,
    ExamineDiscovery,
    ExamineIntent,
    InteractAction,
    ObjectAppend,
)
from playout.referee import apply_action

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


@pytest.fixture
def world(tmp_path):
    w = world_from_scenario(tmp_path / "t.db", SCENARIO)
    yield w
    w.close()


def test_bootstrap_actor_basics(world):
    lena = world.actor("lena")
    assert lena["age"] == 28
    assert lena["sex"] == "女"
    assert lena["occupation"] == "麵包舖主"
    tomas = world.actor("tomas")
    assert tomas["occupation"] == "漁人"
    mara = world.actor("mara")
    assert mara["occupation"] == "船寮管事"
    ellis = world.actor("ellis")
    assert ellis["occupation"] == "放債人"
    rel = world.relationship("lena", "tomas")
    assert rel["nature"] == "couple"
    debt = world.relationship("lena", "ellis")
    assert debt["nature"] == "debt"
    kin = world.relationship("lena", "mara")
    assert kin["nature"] == "kin"


def test_examine_object_grows_and_others_see_it(world):
    vibe = world.location("quay")["description"]
    world.set_actor_location("lena", "quay")
    res = apply_examine(
        world,
        ExamineIntent(actor_id="tomas", aim="quay_rings", intent="刮痕"),
        discovery=ExamineDiscovery(
            perception="你察看空鐵環。圈上有新刮痕，像纜繩被連根抽走。",
            summary="張渡察看空鐵環。",
            object_appends=[
                ObjectAppend(
                    object_id="quay_rings",
                    text="圈上有新刮痕，像纜繩被連根抽走。",
                )
            ],
        ),
    )
    assert res.ok
    assert world.location("quay")["description"] == vibe
    obj = world.object("quay_rings")
    assert obj and "刮痕" in obj["description"]
    node = world.node("quay")
    assert any("刮痕" in o.description for o in node.visible_objects)
    lena_percs = [p["text"] for p in world.perceptions_for("lena", limit=8)]
    assert any("細看" in t for t in lena_percs)
    assert not any("刮痕" in t for t in lena_percs)


def test_examine_place_writes_details_skiff_stays(world):
    vibe = world.location("quay")["description"]
    apply_examine(
        world,
        ExamineIntent(actor_id="tomas", aim="quay", intent="搜看碼頭"),
        discovery=ExamineDiscovery(
            perception="你搜看碼頭。樁腳有新泥。",
            summary="張渡搜看碼頭。",
            location_details=["樁腳有新泥，像有人連夜解纜。"],
            add_objects=[],
        ),
    )
    assert world.location("quay")["description"] == vibe
    details = world.location_detail_texts("quay")
    assert details
    assert "新泥" in details[0]
    assert "新泥" in world.node("quay").description
    skiff = world.object("stolen_skiff")
    assert skiff and skiff["location_id"] == "cliff_path"
    assert skiff["hidden"]


def test_look_toward_does_not_move(world):
    res = apply_examine(
        world, ExamineIntent(actor_id="tomas", aim="boathouse", intent="望去")
    )
    assert res.ok
    assert res.kind == "look_toward"
    assert world.actor("tomas")["location_id"] == "quay"
    skiff = world.object("stolen_skiff")
    assert skiff["location_id"] == "cliff_path"


def test_look_toward_cliff_from_quay_fails_and_stays(world):
    res = apply_examine(
        world, ExamineIntent(actor_id="tomas", aim="cliff_path", intent="望崖")
    )
    assert res.ok is False
    assert res.reason == "not_adjacent"
    assert world.actor("tomas")["location_id"] == "quay"
    assert world.object("stolen_skiff")["location_id"] == "cliff_path"


def test_cannot_spawn_skiff_at_quay(world):
    from playout.models import FoundObject

    apply_examine(
        world,
        ExamineIntent(actor_id="tomas", aim="quay", intent="找船"),
        discovery=ExamineDiscovery(
            perception="你搜看碼頭。空環仍空。",
            summary="張渡搜看碼頭。",
            add_objects=[
                FoundObject(
                    object_id="stolen_skiff",
                    name="失蹤的舢板",
                    description="不該出現在此地。",
                )
            ],
        ),
    )
    skiff = world.object("stolen_skiff")
    assert skiff["location_id"] == "cliff_path"


def test_interact_looking_routes_to_resolver(world):
    deps = ActorDeps(world=world, llm=LLM(), actor_id="tomas")
    result = dispatch_action(deps, InteractAction(text="察看鐵環"))
    assert result.get("ok")
    assert result.get("kind") == "examine"
    ev = world.cx.execute(
        "SELECT kind FROM events WHERE id=?", (result["event_id"],)
    ).fetchone()
    assert ev["kind"] == "examine"
    assert world.actor("tomas")["location_id"] == "quay"


def test_prepare_examine_enum_from_quay(world):
    deps = ActorDeps(world=world, llm=LLM(), actor_id="tomas")
    ctx = SimpleNamespace(deps=deps)
    tool_def = SimpleNamespace(
        parameters_json_schema={
            "type": "object",
            "properties": {"aim": {"type": "string"}},
        }
    )
    out = prepare_examine(ctx, tool_def)
    assert out is not None
    enum = out.parameters_json_schema["properties"]["aim"]["enum"]
    assert "quay" in enum
    assert "quay_rings" in enum
    assert "boathouse" in enum
    assert "cliff_path" not in enum
    assert "stolen_skiff" not in enum
    ids = {i for i, _ in examine_aims(world, "tomas")}
    assert ids == set(enum)


def test_apply_action_examine_object(world):
    r = apply_action(world, "tomas", ExamineAction(target="quay_rings"))
    assert r["ok"]
    percs = [p["text"] for p in world.perceptions_for("tomas", limit=5)]
    assert any("鐵環" in t for t in percs)
