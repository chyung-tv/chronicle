"""Reader snapshot and SSE while a tick is in flight."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from fastapi.testclient import TestClient

from playout.agents import actor as actor_mod
from playout.loop import Simulation
import playout.app as appmod

ROOT_SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


def test_reader_sees_thinking_event_then_idle(tmp_path, monkeypatch):
    sim = Simulation.create(str(tmp_path / "live.db"), ROOT_SCENARIO)
    before = sim.reader.snapshot()
    n_before = len(before["events"])
    assert before["activity"] == "idle"

    barrier = threading.Event()
    released = threading.Event()
    orig = actor_mod.dispatch_action_async

    async def slow(deps, action):
        result = await orig(deps, action)
        barrier.set()
        released.wait(timeout=8)
        return result

    monkeypatch.setattr(actor_mod, "dispatch_action_async", slow)
    th = threading.Thread(target=sim.tick, daemon=True)
    th.start()
    assert barrier.wait(timeout=8), "dispatch never ran"
    mid = sim.reader.snapshot()
    assert mid["activity"] == "thinking"
    assert mid["activity_detail"]
    assert len(mid["events"]) >= n_before
    # tool commit is visible before tick() returns
    assert mid["activity_gen"] > before["activity_gen"]
    released.set()
    th.join(timeout=15)
    idle = sim.reader.snapshot()
    assert idle["activity"] == "idle"
    assert len(idle["events"]) >= len(mid["events"])
    sim.close()


def test_sse_first_frame_is_snapshot(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setenv("PLAYOUT_DB", str(tmp_path / "sse.db"))
    appmod.close_sim()
    appmod.get_sim()

    async def first_frame() -> str:
        response = await appmod.stream()
        assert response.media_type == "text/event-stream"
        agen = response.body_iterator
        chunk = await agen.__anext__()
        await agen.aclose()
        return chunk if isinstance(chunk, str) else chunk.decode()

    buf = asyncio.run(first_frame())
    appmod.close_sim()
    assert buf.startswith("data: ")
    payload = json.loads(buf[len("data: ") :].strip())
    assert payload["title"]
    assert payload["activity"] == "idle"
    assert "events" in payload


def test_tick_command_accepts_without_waiting(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYOUT_DB", str(tmp_path / "cmd.db"))
    appmod.close_sim()
    barrier = threading.Event()
    released = threading.Event()

    with TestClient(appmod.app) as client:
        sim = appmod.get_sim()

        def blocked(*_a, **_k):
            sim.world.set_activity("thinking", detail="held")
            barrier.set()
            released.wait(timeout=8)
            sim.world.set_activity("idle")
            return {"ok": True}

        monkeypatch.setattr(sim, "tick", blocked)
        r = client.post("/api/tick")
        assert r.status_code == 200
        assert r.json() == {"accepted": True}
        assert barrier.wait(timeout=8)
        busy = client.post("/api/tick")
        assert busy.status_code == 409
        snap = client.get("/api/state").json()
        assert snap["activity"] == "thinking"
        released.set()
        for t in list(appmod._workers):
            t.join(timeout=15)
        snap = client.get("/api/state").json()
        assert snap["activity"] == "idle"
    appmod.close_sim()


def test_reset_accepted_idle_gen_bumped(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYOUT_DB", str(tmp_path / "rst.db"))
    appmod.close_sim()
    with TestClient(appmod.app) as client:
        before = client.get("/api/state").json()
        assert before["activity"] == "idle"
        r = client.post("/api/reset")
        assert r.status_code == 200
        assert r.json() == {"accepted": True}
        after = client.get("/api/state").json()
        assert after["activity"] == "idle"
        assert after["activity_gen"] > before["activity_gen"]
        assert after["events"]
    appmod.close_sim()


def test_reset_409_when_busy(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYOUT_DB", str(tmp_path / "rstbusy.db"))
    appmod.close_sim()
    with TestClient(appmod.app) as client:
        sim = appmod.get_sim()
        sim.world.set_activity("thinking", detail="held")
        r = client.post("/api/reset")
        assert r.status_code == 409
        sim.world.set_activity("idle")
    appmod.close_sim()
