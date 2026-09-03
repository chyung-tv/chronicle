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


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYOUT_CATALOG", str(tmp_path / "catalog.db"))
    monkeypatch.setenv("PLAYOUT_STORIES_DIR", str(tmp_path / "stories"))
    appmod.close_runtime()


def _harbors(client: TestClient) -> dict:
    stories = client.get("/api/stories").json()
    return next(s for s in stories if s["slug"] == "harbors-end")


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
    assert mid["activity_gen"] > before["activity_gen"]
    released.set()
    th.join(timeout=15)
    idle = sim.reader.snapshot()
    assert idle["activity"] == "idle"
    assert len(idle["events"]) >= len(mid["events"])
    sim.close()


def test_sse_first_frame_is_snapshot(tmp_path, monkeypatch):
    import asyncio

    from starlette.requests import Request

    _env(tmp_path, monkeypatch)
    with TestClient(appmod.app) as client:
        story = _harbors(client)
        sid = story["id"]

        async def first_frame() -> str:
            request = Request(
                {
                    "type": "http",
                    "asgi": {"version": "3.0"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "path": f"/api/stories/{sid}/stream",
                    "raw_path": f"/api/stories/{sid}/stream".encode(),
                    "query_string": b"",
                    "headers": [],
                    "client": ("testclient", 50000),
                    "server": ("testserver", 80),
                }
            )
            response = await appmod.story_stream(sid, request)
            agen = response.body_iterator
            chunk = await agen.__anext__()
            await agen.aclose()
            return chunk if isinstance(chunk, str) else chunk.decode()

        buf = asyncio.run(first_frame())
    appmod.close_runtime()
    assert buf.startswith("data: ")
    payload = json.loads(buf[len("data: ") :].strip())
    assert payload["title"]
    assert payload["activity"] == "idle"
    assert "events" in payload


def test_tick_command_accepts_without_waiting(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    barrier = threading.Event()
    released = threading.Event()

    with TestClient(appmod.app) as client:
        story = _harbors(client)
        sid = story["id"]
        rec = appmod.get_store().require(sid)
        sim = appmod.get_runtime().get(rec)

        def blocked(*_a, **_k):
            sim.world.set_activity("thinking", detail="held")
            barrier.set()
            released.wait(timeout=8)
            sim.world.set_activity("idle")
            return {"ok": True}

        monkeypatch.setattr(sim, "tick", blocked)
        r = client.post(f"/api/stories/{sid}/tick")
        assert r.status_code == 200
        assert r.json() == {"accepted": True}
        assert barrier.wait(timeout=8)
        busy = client.post(f"/api/stories/{sid}/tick")
        assert busy.status_code == 409
        snap = client.get(f"/api/stories/{sid}/state").json()
        assert snap["activity"] == "thinking"
        released.set()
        for t in list(appmod._workers):
            t.join(timeout=15)
        snap = client.get(f"/api/stories/{sid}/state").json()
        assert snap["activity"] == "idle"
    appmod.close_runtime()


def test_reset_unseals_to_draft(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    with TestClient(appmod.app) as client:
        story = _harbors(client)
        sid = story["id"]
        before = client.get(f"/api/stories/{sid}/state").json()
        assert before["activity"] == "idle"
        r = client.post(f"/api/stories/{sid}/reset")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "draft"
        assert body["editable"] is True
        missing = client.get(f"/api/stories/{sid}/state")
        assert missing.status_code == 409
    appmod.close_runtime()


def test_reset_409_when_busy(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    with TestClient(appmod.app) as client:
        story = _harbors(client)
        rec = appmod.get_store().require(story["id"])
        sim = appmod.get_runtime().get(rec)
        sim.world.set_activity("thinking", detail="held")
        r = client.post(f"/api/stories/{story['id']}/reset")
        assert r.status_code == 409
        sim.world.set_activity("idle")
    appmod.close_runtime()
