"""FastAPI: story catalog + per-story canon API + SSE."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from playout.auth import DEV_USER_ID, User, can_god, get_user, is_owner
from playout.models import StorySetup, StorySketch, empty_setup, empty_sketch
from playout.privacy import redact_setup, redact_snapshot, redact_sketch
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


def catalog_path() -> Path:
    return Path(os.getenv("PLAYOUT_CATALOG", str(ROOT / "catalog.db")))


def stories_dir() -> Path:
    return Path(os.getenv("PLAYOUT_STORIES_DIR", str(ROOT / "data" / "stories")))


def get_store() -> StoryStore:
    global store
    if store is None:
        store = StoryStore(
            catalog_path(),
            stories_dir(),
            database_url=os.getenv("DATABASE_URL") or os.getenv("PLAYOUT_DATABASE_URL"),
        )
    return store


def get_runtime() -> StoryRuntime:
    global runtime
    if runtime is None:
        runtime = StoryRuntime(get_store())
    return runtime


def close_runtime() -> None:
    global runtime, store
    from playout.worker import stop_inline

    stop_inline()
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
    from playout import jobs as jobmod
    from playout.worker import start_inline

    jobmod.ensure_jobs(st)
    if jobmod.worker_mode() == "inline":
        start_inline(st)
    yield
    close_runtime()


app = FastAPI(title="Play Out", lifespan=lifespan)


class TextIn(BaseModel):
    text: str


class StoryCreateIn(BaseModel):
    title: str | None = None
    slug: str | None = None
    setup: StorySetup | None = None
    sketch: StorySketch | None = None


class StoryPatchIn(BaseModel):
    title: str | None = None
    slug: str | None = None
    setup: StorySetup | None = None
    sketch: StorySketch | None = None


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
    from playout import jobs as jobmod

    owner = is_owner(user, rec.owner_id)
    setup = rec.setup()
    sketch = rec.sketch()
    if not owner:
        setup = redact_setup(setup)
        sketch = redact_sketch(sketch)
    return {
        **_card(rec, user),
        "editable": rec.status == "draft" and owner,
        "can_god": can_god(user, rec.owner_id, rec.status),
        "setup": setup,
        "sketch": sketch,
        "agent": jobmod.agent_state(get_store(), rec.id),
    }


def _enqueue(
    rec: StoryRecord,
    kind: str,
    *,
    detail: str,
    actor: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, bool]:
    from playout import jobs as jobmod

    try:
        jobmod.enqueue(
            get_store(),
            rec.id,
            kind,
            payload=payload,
            actor=actor,
            detail=detail,
        )
    except jobmod.Busy:
        raise HTTPException(409, "busy") from None
    return {"accepted": True}


def _transient_pg(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "lock timeout" in msg or "statement timeout" in msg:
        return True
    if "canceling statement" in msg or "locknotavailable" in msg:
        return True
    return False


def _snapshot_for(rec: StoryRecord, user: User) -> dict[str, Any]:
    try:
        snap = get_runtime().snapshot(rec)
    except Exception as e:
        if _transient_pg(e):
            raise HTTPException(503, "busy") from e
        raise
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


@app.get("/api/health")
def health():
    st = get_store()
    try:
        st.cx.execute("SELECT 1")
        return {
            "ok": True,
            "db": "postgres" if st.database_url else "sqlite",
        }
    finally:
        st.cx.rollback()


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
    sketch = data.sketch or empty_sketch(data.title or setup.title)
    if data.title:
        setup.title = data.title
        sketch.title = data.title
    rec = get_store().create(
        user.id, setup, sketch=sketch, slug=data.slug, status="draft"
    )
    return _detail(rec, user)


@app.post("/api/stories/{ref}/wizard")
def wizard_story(ref: str, user: User = Depends(current_user)):
    rec = _story(ref)
    _require_owner(user, rec)
    if rec.status != "draft":
        raise HTTPException(409, "sealed")
    from playout.models import StorySketch

    try:
        StorySketch.model_validate(rec.sketch() or {})
    except Exception as e:
        raise HTTPException(400, f"invalid sketch: {e}") from e
    return _enqueue(rec, "wizard", detail="正在請示巫師…", actor="wizard")


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
            rec.id,
            setup=body.setup,
            sketch=body.sketch,
            title=body.title,
            slug=body.slug,
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
    from playout import jobs as jobmod
    from playout.canon import World

    rec = _story(ref)
    _require_owner(user, rec)
    if jobmod.story_busy(get_store(), rec.id):
        raise HTTPException(409, "busy")
    if rec.status == "live":
        world = World(
            get_store().canon_ref(rec.id),
            readonly=True,
            database_url=get_store().database_url,
        )
        try:
            if (world.meta("activity", "idle") or "idle") != "idle":
                raise HTTPException(409, "busy")
        finally:
            world.close()
    rt = get_runtime()
    try:
        updated = rt.unseal(rec)
    except AlreadyDraft:
        raise HTTPException(409, "already draft") from None
    except RuntimeError as e:
        if str(e) == "busy":
            raise HTTPException(409, "busy") from e
        raise
    return _detail(updated, user)


@app.post("/api/stories/{ref}/unstick")
def unstick_story(ref: str, user: User = Depends(current_user)):
    """Clear a stuck activity=thinking after a worker crash or timeout."""
    from playout import jobs as jobmod
    from playout.canon import World

    rec = _story(ref)
    _require_owner(user, rec)
    if rec.status != "live":
        raise HTTPException(409, "not live")
    st = get_store()
    jobmod.expire_stale(st)
    if jobmod.story_busy(st, rec.id):
        raise HTTPException(409, "busy")
    if st.canon_exists(rec.id):
        world = World(st.canon_ref(rec.id), database_url=st.database_url)
        try:
            world.set_activity("idle")
        finally:
            world.close()
    return _detail(_story(rec.id), user)


@app.get("/api/stories/{ref}/state")
def story_state(ref: str, user: User = Depends(current_user)):
    rec = _story(ref)
    if rec.status != "live":
        raise HTTPException(409, "not live")
    if not get_store().canon_exists(rec.id):
        raise HTTPException(409, "not live")
    return _snapshot_for(rec, user)


@app.get("/api/stories/{ref}/stream")
async def story_stream(ref: str, request: Request):
    from playout.canon import World

    user = get_user(request)
    rec = _story(ref)
    if rec.status != "live":
        raise HTTPException(409, "not live")
    st = get_store()
    if not st.canon_exists(rec.id):
        raise HTTPException(409, "not live")
    world = World(
        st.canon_ref(rec.id),
        readonly=True,
        database_url=st.database_url,
    )

    async def gen():
        last: tuple[Any, ...] | None = None
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    cursor = await asyncio.to_thread(world.stream_cursor)
                    if cursor != last:
                        last = cursor
                        fresh = await asyncio.to_thread(get_store().get, rec.id)
                        if fresh is None or fresh.status != "live":
                            yield ": closed\n\n"
                            return
                        snap = await asyncio.to_thread(_snapshot_for, fresh, user)
                        yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
                    else:
                        yield ": keepalive\n\n"
                except HTTPException:
                    yield ": keepalive\n\n"
                except Exception:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.2)
        finally:
            await asyncio.to_thread(world.close)

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
    if rec.status != "live":
        raise HTTPException(409, "not live")
    return _enqueue(rec, "tick", detail="即將開演")


@app.post("/api/stories/{ref}/day")
def run_day(ref: str, user: User = Depends(current_user)):
    rec = _story(ref)
    if rec.status != "live":
        raise HTTPException(409, "not live")
    return _enqueue(rec, "day", detail="演完今日")


@app.post("/api/stories/{ref}/inject")
def inject(ref: str, body: TextIn, user: User = Depends(current_user)):
    rec = _story(ref)
    _require_owner(user, rec)
    if rec.status != "live":
        raise HTTPException(409, "not live")
    if not body.text.strip():
        raise HTTPException(400, "empty")
    return _enqueue(
        rec,
        "inject",
        detail="神諭注入中",
        actor="storyteller",
        payload={"text": body.text.strip()},
    )


@app.post("/api/stories/{ref}/steer")
def steer(ref: str, body: TextIn, user: User = Depends(current_user)):
    rec = _story(ref)
    _require_owner(user, rec)
    if rec.status != "live":
        raise HTTPException(409, "not live")
    if not body.text.strip():
        raise HTTPException(400, "empty")
    return _enqueue(
        rec,
        "steer",
        detail="導引醞釀中",
        actor="steer",
        payload={"text": body.text.strip()},
    )


@app.post("/api/stories/{ref}/insert-location")
def insert_location(ref: str, body: TextIn, user: User = Depends(current_user)):
    rec = _story(ref)
    _require_owner(user, rec)
    if rec.status != "live":
        raise HTTPException(409, "not live")
    if not body.text.strip():
        raise HTTPException(400, "empty")
    return _enqueue(
        rec,
        "insert_location",
        detail="插入地點中",
        actor="location_writer",
        payload={"text": body.text.strip()},
    )


@app.post("/api/stories/{ref}/insert-actor")
def insert_actor(ref: str, body: TextIn, user: User = Depends(current_user)):
    rec = _story(ref)
    _require_owner(user, rec)
    if rec.status != "live":
        raise HTTPException(409, "not live")
    if not body.text.strip():
        raise HTTPException(400, "empty")
    return _enqueue(
        rec,
        "insert_actor",
        detail="插入人物中",
        actor="actor_writer",
        payload={"text": body.text.strip()},
    )
