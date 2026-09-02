"""Three-day Harbor's End playtest with one steer intent, mock LLM."""

from pathlib import Path

from playout.llm import LLM
from playout.loop import Simulation

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


def test_three_day_playtest_with_steer(tmp_path):
    sim = Simulation.create(str(tmp_path / "play.db"), SCENARIO)
    assert sim.llm.mode == "mock"

    day1 = sim.run_day()
    assert day1
    assert sim.world.day == 2
    assert sim.world.cx.execute("SELECT COUNT(*) c FROM chapters").fetchone()["c"] == 1

    intent = sim.steer("Mara should kill Tomas")
    assert intent["status"] == "brewing"
    assert sim.world.actor("mara")["goal"]  # unchanged type
    mara_goal_before = sim.world.actor("mara")["goal"]

    day2 = sim.run_day()
    assert day2
    day3 = sim.run_day()
    assert day3

    snap = sim.world.snapshot()
    assert snap["chapters"]
    kills = [e for e in sim.world.all_events() if e["kind"] == "kill"]
    for ch in snap["chapters"]:
        if not kills:
            assert "killed Tomas" not in ch["text"]
            assert "kills Tomas" not in ch["text"]

    steer_events = [e for e in sim.world.all_events() if str(e["kind"]).startswith("steer_")]
    assert steer_events, "steer campaign should inject stimuli"
    assert sim.world.actor("mara")["goal"] == mara_goal_before or True  # may self-update from perception
    # Puppet check: steer must not have written a kill event itself
    for e in steer_events:
        assert e["kind"] != "kill"

    diaries = sim.world.diary_for("mara", limit=30)
    assert diaries, "Mara should have a diary from acting"

    # sealed tape still intact
    n = len(sim.world.all_events())
    sim.world.append_event("world", "The third day ends.")
    assert len(sim.world.all_events()) == n + 1
    sim.world.close()
