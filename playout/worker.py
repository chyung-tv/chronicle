"""Claim jobs from Postgres/sqlite and run wizard or live commands."""

from __future__ import annotations

import os
import socket
import threading
import time
from typing import Any

from dotenv import load_dotenv

from playout import jobs
from playout.loop import Simulation
from playout.store import StoryStore

load_dotenv()

_stop = threading.Event()
_thread: threading.Thread | None = None
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"


def _store(existing: StoryStore | None = None) -> StoryStore:
    if existing is not None:
        return existing
    from playout.app import get_store

    return get_store()


def _heartbeat_loop(store: StoryStore, job_id: str, halt: threading.Event) -> None:
    while not halt.wait(15):
        try:
            jobs.heartbeat(store, job_id)
        except Exception:
            return


def _run_wizard(store: StoryStore, job: dict[str, Any]) -> None:
    from playout.llm import LLM
    from playout.models import StorySketch
    from playout.wizard import enrich

    rec = store.require(job["story_id"])
    sketch = StorySketch.model_validate(rec.sketch() or {})
    jobs.bump(store, job["id"], detail="正在請示語言模型", progress=0.35)

    def on_progress(detail: str, progress: float) -> None:
        jobs.bump(store, job["id"], detail=detail, progress=progress)

    setup = enrich(sketch, LLM(), on_progress=on_progress)
    jobs.bump(store, job["id"], detail="正在寫入定稿", progress=0.9)
    store.update_setup(rec.id, setup=setup, sketch=sketch)
    jobs.finish(store, job["id"], status="done", detail="巫師已補完")


def _run_live(store: StoryStore, job: dict[str, Any]) -> None:
    rec = store.require(job["story_id"])
    if rec.status != "live":
        raise RuntimeError("not live")
    sim = Simulation.open_existing(
        store.canon_ref(rec.id), database_url=store.database_url
    )
    try:
        kind = job["kind"]
        payload = job.get("payload") or {}
        if kind == "tick":
            sim.tick()
        elif kind == "day":
            sim.run_day()
        elif kind == "inject":
            sim.inject(str(payload.get("text") or ""))
        elif kind == "steer":
            sim.steer(str(payload.get("text") or ""))
        elif kind == "insert_location":
            sim.insert_location(str(payload.get("text") or ""))
        elif kind == "insert_actor":
            sim.insert_actor(str(payload.get("text") or ""))
        else:
            raise RuntimeError(f"unknown job kind {kind}")
        jobs.finish(store, job["id"], status="done", detail="完成")
    except Exception:
        try:
            sim.world.set_activity("idle", error="失敗")
        except Exception:
            pass
        raise
    finally:
        sim.close()


def run_job(store: StoryStore, job: dict[str, Any]) -> None:
    halt = threading.Event()
    beater = threading.Thread(
        target=_heartbeat_loop, args=(store, job["id"], halt), daemon=True
    )
    beater.start()
    try:
        if job["kind"] == "wizard":
            _run_wizard(store, job)
        else:
            _run_live(store, job)
    except Exception as e:
        try:
            jobs.finish(
                store,
                job["id"],
                status="error",
                error=str(e)[:500],
                detail="失敗",
            )
        except Exception:
            pass
    finally:
        halt.set()


def run_one(store: StoryStore | None = None) -> bool:
    st = _store(store)
    jobs.ensure_jobs(st)
    claimed = jobs.claim_one(st, WORKER_ID)
    if not claimed:
        return False
    run_job(st, claimed)
    return True


def run_until_empty(store: StoryStore | None = None, *, limit: int = 32) -> int:
    n = 0
    while n < limit and run_one(store):
        n += 1
    return n


def loop(store: StoryStore | None = None) -> None:
    st = _store(store)
    jobs.ensure_jobs(st)
    while not _stop.is_set():
        if not run_one(st):
            _stop.wait(0.4)


def start_inline(store: StoryStore | None = None) -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()

    def work() -> None:
        loop(store)

    _thread = threading.Thread(target=work, daemon=True, name="playout-worker")
    _thread.start()


def stop_inline() -> None:
    global _thread
    _stop.set()
    t = _thread
    _thread = None
    if t is not None:
        t.join(timeout=8)


def main() -> None:
    from playout.app import catalog_path, close_runtime, stories_dir
    from playout.store import StoryStore

    st = StoryStore(
        catalog_path(),
        stories_dir(),
        database_url=os.getenv("DATABASE_URL") or os.getenv("PLAYOUT_DATABASE_URL"),
    )
    try:
        jobs.ensure_jobs(st)
        loop(st)
    finally:
        st.close()
        close_runtime()


if __name__ == "__main__":
    main()
