from pathlib import Path

import pytest

from playout.canon import World, world_from_scenario

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


@pytest.fixture
def world(tmp_path):
    w = world_from_scenario(tmp_path / "t.db", SCENARIO)
    yield w
    w.close()


def test_bootstrap_counts(world):
    assert world.meta("title") == "Harbor's End"
    assert len(world.living_actors()) == 4
    assert world.cx.execute("SELECT COUNT(*) c FROM locations").fetchone()["c"] == 6
    assert world.all_events()


def test_events_are_sealed(world):
    eid = world.append_event("world", "A gull screams.")
    with pytest.raises(Exception):
        world.cx.execute("UPDATE events SET summary='nope' WHERE id=?", (eid,))
        world.cx.commit()
    world.cx.rollback()
    with pytest.raises(Exception):
        world.cx.execute("DELETE FROM events WHERE id=?", (eid,))
        world.cx.commit()
    world.cx.rollback()
    row = world.cx.execute("SELECT summary FROM events WHERE id=?", (eid,)).fetchone()
    assert row["summary"] == "A gull screams."


def test_diaries_are_sealed(world):
    world.write_diary("lena", "I am tired.", 5)
    with pytest.raises(Exception):
        world.cx.execute("UPDATE diaries SET text='rewritten' WHERE actor_id='lena'")
        world.cx.commit()
    world.cx.rollback()


def test_epistemic_perceptions_are_per_actor(world):
    eid = world.append_event("speak", "secret between Tomas and Ellis", actor_id="tomas", target_id="ellis")
    world.perceive(eid, "tomas", "You told Ellis.")
    world.perceive(eid, "ellis", "Tomas told you.")
    mara = world.perceptions_for("mara")
    assert not any("Tomas told you" in p["text"] or "You told Ellis" in p["text"] for p in mara)
