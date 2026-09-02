from pathlib import Path

import pytest

from playout.canon import world_from_scenario
from playout.llm import LLM
from playout.writer import validate_chapter, write_day
from playout.models import WriterChapter

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


@pytest.fixture
def world(tmp_path):
    w = world_from_scenario(tmp_path / "t.db", SCENARIO)
    yield w
    w.close()


def test_writer_strips_invented_death(world):
    fake = WriterChapter(
        pov="lena",
        tags=["violence"],
        cited_event_ids=[1],
        text="Then Mara killed Tomas in the boathouse. The corpse cooled.",
    )
    out = validate_chapter(world, 1, fake)
    assert "killed" not in out.text.lower()
    assert "corpse" not in out.text.lower()


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
