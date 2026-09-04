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
    assert world.meta("title") == "港尾"
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
    eid = world.append_event(
        "speak", "secret between Tomas and Ellis", actor_id="tomas", target_id="ellis"
    )
    world.perceive(eid, "tomas", "You told Ellis.")
    world.perceive(eid, "ellis", "Tomas told you.")
    mara = world.perceptions_for("mara")
    assert not any(
        "Tomas told you" in p["text"] or "You told Ellis" in p["text"] for p in mara
    )


def test_node_and_atmosphere(world):
    node = world.node("quay")
    assert node.name == "碼頭"
    assert "鐵環" in node.description or "樁" in node.description
    ids = {e.id for e in world.exits("quay")}
    assert ids == {"bakery", "inn", "boathouse"}
    atmo = world.atmosphere()
    assert atmo.title == "港尾"
    assert atmo.weather


class _CanonCx:
    def __init__(self, ready: bool):
        self.ready = ready
        self.sqls: list[str] = []
        self.commits = 0

    def execute(self, sql, params=()):
        self.sqls.append(sql)
        cx = self

        class Cur:
            def fetchone(self):
                if cx.ready and "information_schema.tables" in sql:
                    return {"ok": 1}
                return None

            def fetchall(self):
                if "information_schema.columns" in sql:
                    return [{"name": "condition"}]
                return []

        return Cur()

    def executescript(self, script):
        self.sqls.append(script)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def test_apply_postgres_canon_skips_triggers_when_ready():
    from playout.canon import apply_postgres_canon

    cx = _CanonCx(ready=True)
    apply_postgres_canon(cx)
    joined = "\n".join(cx.sqls)
    assert "DROP TRIGGER" not in joined.upper()
    assert "CREATE TRIGGER" not in joined.upper()
    assert "CREATE OR REPLACE FUNCTION" not in joined.upper()


def test_apply_postgres_canon_seals_new_schema():
    from playout.canon import apply_postgres_canon

    cx = _CanonCx(ready=False)
    apply_postgres_canon(cx)
    joined = "\n".join(cx.sqls)
    assert "DROP TRIGGER" in joined.upper()
    assert "CREATE TRIGGER" in joined.upper()
    assert cx.commits >= 1


def test_reader_snapshot_releases(world):
    reader = world.reader()
    try:
        snap = reader.snapshot()
        assert snap["title"] == "港尾"
        cur = reader.stream_cursor()
        assert cur[0] >= 0
    finally:
        reader.close()
