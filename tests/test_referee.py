from pathlib import Path

import pytest

from playout.canon import world_from_scenario
from playout.models import KillAction, MoveAction, SpeakAction
from playout.referee import apply_action

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


@pytest.fixture
def world(tmp_path):
    w = world_from_scenario(tmp_path / "t.db", SCENARIO)
    yield w
    w.close()


def test_cannot_speak_across_town(world):
    # lena bakery, ellis inn
    r = apply_action(world, "lena", SpeakAction(target="ellis", speech="Pay later."))
    assert r["ok"] is False


def test_move_only_adjacent(world):
    r = apply_action(world, "lena", MoveAction(to="boathouse"))
    assert r["ok"] is False
    r = apply_action(world, "lena", MoveAction(to="quay"))
    assert r["ok"] is True
    assert world.actor("lena")["location_id"] == "quay"


def test_kill_requires_colocation(world):
    r = apply_action(world, "mara", KillAction(target="tomas"))
    assert r["ok"] is False
    world.set_actor_location("mara", "quay")
    world.set_actor_location("tomas", "quay")
    r = apply_action(world, "mara", KillAction(target="tomas"))
    # no weapon, tomas not injured → attempted
    assert r["ok"] is True
    assert r.get("killed") is False
    assert world.actor("tomas")["alive"]
    assert world.actor("tomas")["injured"]
