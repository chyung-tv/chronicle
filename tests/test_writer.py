from pathlib import Path

import pytest

from playout.canon import world_from_scenario
from playout.llm import LLM
from playout.models import KillAction, SpeakAction, WriterChapter
from playout.referee import apply_action
from playout.writer import validate_chapter, write_day, writer_pack

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


@pytest.fixture
def world(tmp_path):
    w = world_from_scenario(tmp_path / "t.db", SCENARIO)
    yield w
    w.close()


def test_validate_keeps_real_death_words(world):
    world.set_actor_location("mara", "quay")
    world.set_actor_location("tomas", "quay")
    world.set_injured("tomas", True)
    r = apply_action(world, "mara", KillAction(target="tomas"))
    assert r.get("killed") is True
    day = world.day
    fake = WriterChapter(
        pov="mara",
        tags=["暴力"],
        cited_event_ids=[r["event_id"]],
        text="然後關瑪在碼頭殺了張渡。屍體涼了。",
    )
    out = validate_chapter(world, day, fake)
    assert "殺了" in out.text
    assert "屍體" in out.text


def test_writer_pack_includes_speech_and_locations(world):
    world.set_actor_location("mara", "quay")
    r = apply_action(
        world, "tomas", SpeakAction(target="mara", speech="風要來了。")
    )
    pack = writer_pack(world, world.day)
    speak = next(row for row in pack["tape"] if row["id"] == r["event_id"])
    assert speak["payload"]["speeches"][0]["text"] == "風要來了。"
    loc_ids = {n["id"] for n in pack["locations"]}
    assert "quay" in loc_ids
    quay = next(n for n in pack["locations"] if n["id"] == "quay")
    assert quay["description"]


def test_writer_chapter_cites_tape(world):
    llm = LLM()
    ch = write_day(world, llm, 1)
    assert ch["text"]
    assert ch["cited_event_ids"]
    row = world.cx.execute("SELECT text FROM chapters WHERE day=1").fetchone()
    assert row
    with pytest.raises(Exception):
        world.cx.execute("UPDATE chapters SET text='fanfic' WHERE day=1")
        world.cx.commit()
    world.cx.rollback()
