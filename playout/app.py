"""FastAPI: story catalog + per-story canon API + SSE."""

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
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from playout.auth import DEV_USER_ID, User, can_god, get_user, is_owner
from playout.loop import Simulation
from playout.models import StorySetup, empty_setup
from playout.privacy import redact_setup, redact_snapshot
from playout.runtime import StoryRuntime
from playout.store import (
    AlreadyDraft,
    AlreadyLive,
    NotFound,
    SealedError,
    SlugTaken,
    StoreError,
    StoryRecord,
    StoryStore,
)

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

store: StoryStore | None = None
runtime: StoryRuntime | None = None
_workers: list[threading.Thread] = []


def catalog_path() -> Path:
    return Path(os.getenv("PLAYOUT_CATALOG", str(ROOT / "catalog.db")))


def stories_dir() -> Path:
    return Path(os.getenv("PLAYOUT_STORIES_DIR", str(ROOT / "data" / "stories")))


def get_store() -> StoryStore:
    global store
    if store is None:
        store = StoryStore(catalog_path(), stories_dir())
    return store


def get_runtime() -> StoryRuntime:
    global runtime
    if runtime is None:
        runtime = StoryRuntime(get_store())
    return runtime


def close_runtime() -> None:
    global runtime, store
    for t in list(_workers):
        t.join(timeout=60)
    _workers.clear()
    if runtime is not None:
        runtime.close()
        runtime = None
    if store is not None:
        store.close()
        store = None


# Back-compat alias used by older tests; now tears down catalog + runtimes.
close_sim = close_runtime


@asynccontextmanager
async def lifespan(_app: FastAPI):
    st = get_store()
    st.seed_harbors_end(DEV_USER_ID)
    get_runtime()
    yield
    close_runtime()


app = FastAPI(title="Play Out", lifespan=lifespan)


class TextIn(BaseModel):
    text: str


class StoryCreateIn(BaseModel):
    title: str | None = None
    slug: str | None = None
    setup: StorySetup | None = None


class StoryPatchIn(BaseModel):
    title: str | None = None
    slug: str | None = None
    setup: StorySetup | None = None


def current_user(request: Request) -> User:
    return get_user(request)


def _story(ref: str) -> StoryRecord:
    rec = get_store().get(ref)
    if rec is None:
        raise HTTPException(404, "story not found")
    return rec


def _require_owner(user: User, rec: StoryRecord) -> None:
    if not is_owner(user, rec.owner_id):
        raise HTTPException(403, "not owner")


def _busy(sim: Simulation) -> bool:
    return (sim.world.meta("activity", "idle") or "idle") != "idle"


def _http_store(exc: StoreError) -> None:
    if isinstance(exc, NotFound):
        raise HTTPException(404, "story not found") from exc
    if isinstance(exc, SealedError):
        raise HTTPException(409, "sealed") from exc
    if isinstance(exc, AlreadyLive):
        raise HTTPException(409, "already live") from exc
    if isinstance(exc, AlreadyDraft):
        raise HTTPException(409, "already draft") from exc
    if isinstance(exc, SlugTaken):
        raise HTTPException(409, "slug taken") from exc
    raise HTTPException(400, str(exc)) from exc


def _card(rec: StoryRecord, user: User) -> dict[str, Any]:
    setup = rec.setup()
    day = get_store().peek_day(rec)
    return {
        "id": rec.id,
        "slug": rec.slug,
        "title": rec.title,
        "owner_id": rec.owner_id,
        "is_owner": is_owner(user, rec.owner_id),
        "status": rec.status,
        "day": day,
        "actor_count": len(setup.get("actors") or []),
        "location_count": len(setup.get("locations") or []),
        "created_at": rec.created_at,
        "updated_at": rec.updated_at,
    }


def _detail(rec: StoryRecord, user: User) -> dict[str, Any]:
    owner = is_owner(user, rec.owner_id)
    setup = rec.setup()
    if not owner:
        setup = redact_setup(setup)
    return {
        **_card(rec, user),
        "editable": rec.status == "draft" and owner,
        "can_god": can_god(user, rec.owner_id, rec.status),
        "setup": setup,
    }


def _accept(
    sim: Simulation,
    fn: Callable[[], Any],
    *,
    activity: str,
    actor: str = "",
    detail: str = "",
) -> dict[str, bool]:
    with sim._lock:
        if _busy(sim):
            raise HTTPException(409, "busy")
        sim.world.set_activity(activity, actor=actor, detail=detail, error="")

    def work() -> None:
        try:
            fn()
        except Exception as e:
            try:
                sim.world.set_activity("idle", error=str(e)[:500])
            except Exception:
                pass

    t = threading.Thread(target=work, daemon=True, name="playout-cmd")
    _workers.append(t)
    t.start()
    return {"accepted": True}


def _live_sim(rec: StoryRecord) -> Simulation:
    if rec.status != "live":
        raise HTTPException(409, "not live")
    try:
        return get_runtime().get(rec)
    except FileNotFoundError:
        raise HTTPException(409, "not live") from None
    except AlreadyDraft:
        raise HTTPException(409, "not live") from None


def _snapshot_for(rec: StoryRecord, user: User) -> dict[str, Any]:
    snap = get_runtime().snapshot(rec)
    owner = is_owner(user, rec.owner_id)
    if not owner:
        snap = redact_snapshot(snap)
    snap["story_id"] = rec.id
    snap["slug"] = rec.slug
    snap["is_owner"] = owner
    snap["can_god"] = can_god(user, rec.owner_id, rec.status)
    return snap


@app.get("/")
def index():
    return {
        "ok": True,
        "ui": os.getenv("PLAYOUT_UI_ORIGIN", "http://127.0.0.1:3000"),
        "stories": "/api/stories",
    }


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    resp = JSONResponse({"id": user.id, "name": user.name})
    # Cookie values must be latin-1; keep the id (ASCII). Name lives on the JSON body.
    resp.set_cookie("playout_user", user.id, httponly=False, samesite="lax", path="/")
    return resp


@app.get("/api/stories")
def list_stories(user: User = Depends(current_user)):
    return [_card(rec, user) for rec in get_store().list()]


@app.post("/api/stories")
def create_story(
    user: User = Depends(current_user),
    body: StoryCreateIn | None = Body(default=None),
):
    data = body or StoryCreateIn()
    setup = data.setup or empty_setup(data.title or "未名")
    if data.title:
        setup.title = data.title
    rec = get_store().create(user.id, setup, slug=data.slug, status="draft")
    return _detail(rec, user)


@app.post("/api/stories/{ref}/duplicate")
def duplicate_story(ref: str, user: User = Depends(current_user)):
    rec = _story(ref)
    copy = get_store().duplicate(rec.id, user.id)
    return _detail(copy, user)


@app.get("/api/stories/{ref}")
def get_story(ref: str, user: User = Depends(current_user)):
    return _detail(_story(ref), user)


@app.patch("/api/stories/{ref}")
def patch_story(
    ref: str, body: StoryPatchIn, user: User = Depends(current_user)
):
    rec = _story(ref)
    _require_owner(user, rec)
    try:
        updated = get_store().update_setup(
            rec.id, setup=body.setup, title=body.title, slug=body.slug
        )
    except StoreError as e:
        _http_store(e)
    return _detail(updated, user)


@app.post("/api/stories/{ref}/start")
def start_story(ref: str, user: User = Depends(current_user)):
    rec = _story(ref)
    _require_owner(user, rec)
    try:
        get_runtime().start(rec)
    except AlreadyLive:
        raise HTTPException(409, "already live") from None
    return _detail(_story(rec.id), user)


@app.post("/api/stories/{ref}/reset")
def reset_story(ref: str, user: User = Depends(current_user)):
    """TEMPORARY unseal: drop canon, return to draft. Remove when stories are unique."""
    rec = _story(ref)
    _require_owner(user, rec)
    rt = get_runtime()
    try:
        sim = rt._sims.get(rec.id)
        if sim is not None and _busy(sim):
            raise HTTPException(409, "busy")
        updated = rt.unseal(rec)
    except AlreadyDraft:
        raise HTTPException(409, "already draft") from None
    except RuntimeError as e:
        if str(e) == "busy":
            raise HTTPException(409, "busy") from e
        raise
    return _detail(updated, user)


@app.get("/api/stories/{ref}/state")
def story_state(ref: str, user: User = Depends(current_user)):
    rec = _story(ref)
    _live_sim(rec)
    return _snapshot_for(rec, user)


@app.get("/api/stories/{ref}/stream")
async def story_stream(ref: str, request: Request):
    user = get_user(request)
    rec = _story(ref)
    sim = _live_sim(rec)

    async def gen():
        last: tuple[Any, ...] | None = None
        while True:
            try:
                cursor = sim.reader.stream_cursor()
                if cursor != last:
                    last = cursor
                    fresh = get_store().get(rec.id)
                    if fresh is None or fresh.status != "live":
                        yield ": closed\n\n"
                        return
                    snap = _snapshot_for(fresh, user)
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


@app.post("/api/stories/{ref}/tick")
def tick(ref: str, user: User = Depends(current_user)):
    rec = _story(ref)
    sim = _live_sim(rec)
    return _accept(sim, sim.tick, activity="thinking", detail="即將開演")


@app.post("/api/stories/{ref}/day")
def run_day(ref: str, user: User = Depends(current_user)):
    rec = _story(ref)
    sim = _live_sim(rec)
    return _accept(sim, sim.run_day, activity="thinking", detail="演完今日")


@app.post("/api/stories/{ref}/inject")
def inject(ref: str, body: TextIn, user: User = Depends(current_user)):
    rec = _story(ref)
    _require_owner(user, rec)
    if rec.status != "live":
        raise HTTPException(409, "not live")
    if not body.text.strip():
        raise HTTPException(400, "empty")
    sim = _live_sim(rec)
    return _accept(
        sim,
        lambda: sim.inject(body.text.strip()),
        activity="injecting",
        actor="storyteller",
        detail="神諭注入中",
    )


@app.post("/api/stories/{ref}/steer")
def steer(ref: str, body: TextIn, user: User = Depends(current_user)):
    rec = _story(ref)
    _require_owner(user, rec)
    if rec.status != "live":
        raise HTTPException(409, "not live")
    if not body.text.strip():
        raise HTTPException(400, "empty")
    sim = _live_sim(rec)
    return _accept(
        sim,
        lambda: sim.steer(body.text.strip()),
        activity="steering",
        actor="steer",
        detail="導引醞釀中",
    )
