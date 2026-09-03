"""Reader snapshot and SSE while a tick is in flight."""

from __future__ import annotations

import json
import threading
import time
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

    orig = Simulation.tick

    def blocked(self, *a, **k):
        self.world.set_activity("thinking", detail="held")
        barrier.set()
        released.wait(timeout=8)
        self.world.set_activity("idle")
        return {"ok": True}

    monkeypatch.setattr(Simulation, "tick", blocked)

    with TestClient(appmod.app) as client:
        story = _harbors(client)
        sid = story["id"]
        r = client.post(f"/api/stories/{sid}/tick")
        assert r.status_code == 200
        assert r.json() == {"accepted": True}
        assert barrier.wait(timeout=8)
        busy = client.post(f"/api/stories/{sid}/tick")
        assert busy.status_code == 409
        snap = client.get(f"/api/stories/{sid}/state").json()
        assert snap["activity"] == "thinking"
        released.set()
        idle = None
        for _ in range(50):
            idle = client.get(f"/api/stories/{sid}/state").json()
            if idle["activity"] == "idle":
                break
            time.sleep(0.1)
        assert idle is not None
        assert idle["activity"] == "idle"
    monkeypatch.setattr(Simulation, "tick", orig)
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
    from playout.canon import World

    _env(tmp_path, monkeypatch)
    with TestClient(appmod.app) as client:
        story = _harbors(client)
        store = appmod.get_store()
        world = World(
            store.canon_ref(story["id"]), database_url=store.database_url
        )
        world.set_activity("thinking", detail="held")
        world.close()
        r = client.post(f"/api/stories/{story['id']}/reset")
        assert r.status_code == 409
        world = World(
            store.canon_ref(story["id"]), database_url=store.database_url
        )
        world.set_activity("idle")
        world.close()
    appmod.close_runtime()
