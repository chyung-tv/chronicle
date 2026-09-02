"""FastAPI: canon API + SSE. UI is the Next.js app on port 3000."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from playout.loop import SCENARIO, Simulation

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def db_path() -> Path:
    return Path(os.getenv("PLAYOUT_DB", str(ROOT / "playout.db")))

sim: Simulation | None = None
_workers: list[threading.Thread] = []


def get_sim() -> Simulation:
    global sim
    if sim is None:
        sim = Simulation.open(str(db_path()), str(SCENARIO))
    return sim


def close_sim() -> None:
    global sim
    for t in list(_workers):
        t.join(timeout=60)
    _workers.clear()
    if sim is not None:
        sim.close()
        sim = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_sim()
    yield
    close_sim()


app = FastAPI(title="Play Out", lifespan=lifespan)


class TextIn(BaseModel):
    text: str


def _busy(world) -> bool:
    return (world.meta("activity", "idle") or "idle") != "idle"


def _accept(
    fn: Callable[[], Any],
    *,
    activity: str,
    actor: str = "",
    detail: str = "",
) -> dict[str, bool]:
    s = get_sim()
    with s._lock:
        if _busy(s.world):
            raise HTTPException(409, "busy")
        s.world.set_activity(activity, actor=actor, detail=detail, error="")

    def work() -> None:
        try:
            fn()
        except Exception as e:
            try:
                s.world.set_activity("idle", error=str(e)[:500])
            except Exception:
                pass

    t = threading.Thread(target=work, daemon=True, name="playout-cmd")
    _workers.append(t)
    t.start()
    return {"accepted": True}


def _snapshot() -> dict[str, Any]:
    return get_sim().reader.snapshot()


def _cursor() -> tuple[Any, ...]:
    return get_sim().reader.stream_cursor()


@app.get("/")
def index():
    return {
        "ok": True,
        "ui": os.getenv("PLAYOUT_UI_ORIGIN", "http://127.0.0.1:3000"),
        "stream": "/api/stream",
    }


@app.get("/api/state")
def state():
    return _snapshot()


@app.get("/api/stream")
async def stream():
    async def gen():
        last: tuple[Any, ...] | None = None
        while True:
            try:
                cursor = _cursor()
                if cursor != last:
                    last = cursor
                    snap = _snapshot()
                    yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
                else:
                    yield ": keepalive\n\n"
            except Exception:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/tick")
def tick():
    s = get_sim()
    return _accept(s.tick, activity="thinking", detail="即將開演")


@app.post("/api/day")
def run_day():
    s = get_sim()
    return _accept(s.run_day, activity="thinking", detail="演完今日")


@app.post("/api/inject")
def inject(body: TextIn):
    if not body.text.strip():
        raise HTTPException(400, "empty")
    s = get_sim()
    return _accept(
        lambda: s.inject(body.text.strip()),
        activity="injecting",
        actor="storyteller",
        detail="神諭注入中",
    )


@app.post("/api/steer")
def steer(body: TextIn):
    if not body.text.strip():
        raise HTTPException(400, "empty")
    s = get_sim()
    return _accept(
        lambda: s.steer(body.text.strip()),
        activity="steering",
        actor="steer",
        detail="導引醞釀中",
    )


@app.post("/api/reset")
def reset():
    global sim
    s = get_sim()
    with s._lock:
        if _busy(s.world):
            raise HTTPException(409, "busy")
        try:
            s.reader.close()
        except Exception:
            pass
        s.world.close()
        sim = None
        path = db_path()
        if path.exists():
            path.unlink()
        for suffix in ("-wal", "-shm"):
            p = Path(str(path) + suffix)
            if p.exists():
                p.unlink()
        sim = Simulation.create(str(path), str(SCENARIO))
        sim.world.set_activity("idle")
    return {"accepted": True}
