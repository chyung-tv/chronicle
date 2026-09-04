from pathlib import Path

import pytest

from playout.canon import world_from_scenario
from playout.llm import LLM
from playout.steer import submit_intent, tick_intents

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


@pytest.fixture
def world(tmp_path):
    w = world_from_scenario(tmp_path / "t.db", SCENARIO)
    yield w
    w.close()


def test_parse_pair_uses_text_order():
    from playout.steer import _parse_pair

    actors = [
        {"id": "tomas", "name": "Tomas Reed"},
        {"id": "mara", "name": "Mara Quinn"},
        {"id": "lena", "name": "Lena Vale"},
    ]
    a, b = _parse_pair("Mara should kill Tomas", actors)
    assert a == "mara"
    assert b == "tomas"


def test_parse_pair_chinese_names():
    from playout.steer import _parse_pair

    actors = [
        {"id": "tomas", "name": "張渡"},
        {"id": "mara", "name": "關瑪"},
        {"id": "lena", "name": "林樂安"},
    ]
    a, b = _parse_pair("關瑪應當殺了張渡", actors)
    assert a == "mara"
    assert b == "tomas"


def test_steer_does_not_puppet_a_kill(world):
    llm = LLM()
    assert llm.mode == "mock"
    out = submit_intent(world, llm, "Mara should kill Tomas")
    assert out["status"] == "brewing"
    tick_intents(world)
    kills = [e for e in world.all_events() if e["kind"] == "kill"]
    assert kills == []
    assert world.actor("tomas")["alive"]
    assert "kill" not in world.actor("mara")["goal"].lower()
    assert out["campaign"]["summary"].startswith("令關瑪有機會傷害張渡")


def test_steer_injects_new_events_only(world):
    llm = LLM()
    n = len(world.all_events())
    submit_intent(world, llm, "Mara should ruin Tomas")
    tick_intents(world)
    events = world.all_events()
    assert len(events) > n
    assert any(e["kind"].startswith("steer_") for e in events)
    diaries = world.cx.execute("SELECT text FROM diaries").fetchall()
    # steer must not write diaries
    assert diaries == []


def test_forbidden_ops_stripped(world):
    from playout.models import Patch, SteerCampaign, SteerRung, StorytellerPlan
    from playout.steer import _forbidden_ops

    bad = SteerCampaign(
        summary="x",
        rungs=[
            SteerRung(
                id="motive",
                kind="motive",
                injection=StorytellerPlan(
                    summary="no",
                    patches=[
                        Patch(op="kill_actor", actor_id="tomas", detail="nope"),
                        Patch(op="rumor", actor_ids=["mara"], detail="ok"),
                    ],
                ),
            )
        ],
    )
    cleaned = _forbidden_ops(bad)
    assert all(p.op != "kill_actor" for p in cleaned.rungs[0].injection.patches)
    assert any(p.op == "rumor" for p in cleaned.rungs[0].injection.patches)


def test_forbidden_ops_keeps_spawn():
    from playout.models import Patch, SteerCampaign, SteerRung, StorytellerPlan
    from playout.steer import _forbidden_ops

    camp = SteerCampaign(
        summary="x",
        rungs=[
            SteerRung(
                id="motive",
                kind="motive",
                injection=StorytellerPlan(
                    summary="shop",
                    patches=[
                        Patch(
                            op="add_location",
                            location_id="shop",
                            name="店",
                            connect_to="quay",
                        ),
                        Patch(op="destroy_location", location_id="quay", detail="no"),
                    ],
                ),
            )
        ],
    )
    cleaned = _forbidden_ops(camp)
    ops = [p.op for p in cleaned.rungs[0].injection.patches]
    assert "add_location" in ops
    assert "destroy_location" not in ops
