"""House voice: 香港書面語, not 章回, not 粵語口語入文."""

from __future__ import annotations

import json
from pathlib import Path

from playout.canon import world_from_scenario
from playout.models import empty_setup
from playout.wizard import WIZARD_SYSTEM
from playout.writer import WRITER_SYSTEM, _heuristic_chapter
from playout.zh import DESC_UNSET, PROSE, VOICE_UNSET, WANT_UNSET, say

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


def test_house_prose_is_hk_written():
    assert "香港繁體中文書面語" in PROSE
    assert "台灣" not in PROSE
    assert "不要章回體" in PROSE
    assert "不要把整段寫成粵語口語入文" in PROSE
    assert say("林樂安", "風要來了。", "張渡") == "林樂安對張渡說：「風要來了。」"
    assert say("張渡", "風要來了。") == "張渡說：「風要來了。」"


def test_writer_and_wizard_prompts_use_hk_written():
    assert "章回正文" not in WRITER_SYSTEM
    assert "章節正文" in WRITER_SYSTEM
    assert "香港繁體中文書面語" in WIZARD_SYSTEM
    assert "不要把設定正文寫成粵語口語" in WIZARD_SYSTEM


def test_harbors_end_demo_is_hk_written():
    raw = json.loads(SCENARIO.read_text(encoding="utf-8"))
    blob = json.dumps(raw, ensure_ascii=False)
    assert raw["setup"]["title"] == "港尾"
    assert "新界" in blob
    assert "漁港" in blob
    assert "章回" not in blob
    assert "道：「" not in blob
    assert "客棧" not in blob
    assert raw["setup"]["locations"][1]["name"] == "鹹燈旅館"


def test_heuristic_chapter_is_hk_written(tmp_path):
    world = world_from_scenario(tmp_path / "t.db", SCENARIO)
    try:
        empty = _heuristic_chapter(world, 1, [])
        assert "章回" not in empty.text
        assert "無事的光陰" not in empty.text
        assert "沒有甚麼事" in empty.text
        filled = _heuristic_chapter(world, 1, world.events_for_day(1))
        assert "章回" not in filled.text
        assert "這邊看" in filled.text or "沒有甚麼事" in filled.text
    finally:
        world.close()


def test_speak_tape_uses_shuo_not_dao(tmp_path):
    from playout.models import SpeakAction
    from playout.referee import apply_action

    world = world_from_scenario(tmp_path / "t.db", SCENARIO)
    try:
        world.set_actor_location("mara", "quay")
        result = apply_action(
            world, "tomas", SpeakAction(target="mara", speech="風要來了。")
        )
        row = world.cx.execute(
            "SELECT summary FROM events WHERE id=?", (result["event_id"],)
        ).fetchone()
        assert "說：「風要來了。」" in row["summary"]
        assert "道：「" not in row["summary"]
    finally:
        world.close()


def test_empty_setup_sentinels_are_hk_written():
    setup = empty_setup()
    assert setup.actors[0].voice == VOICE_UNSET
    assert setup.actors[0].want == WANT_UNSET
    assert setup.locations[0].description == DESC_UNSET
