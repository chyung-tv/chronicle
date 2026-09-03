"""Postgres (and sqlite) job broker. Unique active job per story is the busy lock."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from playout.store import StoryStore

JOBS_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    progress REAL NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    gen INTEGER NOT NULL DEFAULT 0,
    heartbeat_at TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    locked_by TEXT
);
"""

STALE_AFTER = timedelta(minutes=3)

IDLE_AGENT = {
    "kind": "",
    "status": "idle",
    "actor": "",
    "detail": "",
    "progress": 0.0,
    "gen": 0,
    "error": "",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _row(r: Any) -> dict[str, Any]:
    if r is None:
        return {}
    payload = r["payload"]
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode()
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    try:
        parsed = json.loads(payload or "{}")
    except json.JSONDecodeError:
        parsed = {}
    return {
        "id": r["id"],
        "story_id": r["story_id"],
        "kind": r["kind"],
        "payload": parsed if isinstance(parsed, dict) else {},
        "status": r["status"],
        "actor": r["actor"] or "",
        "detail": r["detail"] or "",
        "progress": float(r["progress"] or 0),
        "error": r["error"] or "",
        "gen": int(r["gen"] or 0),
        "heartbeat_at": r["heartbeat_at"],
        "created_at": r["created_at"],
        "started_at": r["started_at"],
        "finished_at": r["finished_at"],
        "locked_by": r["locked_by"],
    }


def agent_from_job(job: dict[str, Any] | None) -> dict[str, Any]:
    if not job:
        return dict(IDLE_AGENT)
    status = job["status"]
    if status in ("done",):
        # Keep last detail at 1.0 so the UI can flash completion, then idle.
        return {
            "kind": job["kind"],
            "status": "done",
            "actor": job["actor"],
            "detail": job["detail"],
            "progress": 1.0,
            "gen": job["gen"],
            "error": "",
        }
    if status == "error":
        return {
            "kind": job["kind"],
            "status": "error",
            "actor": job["actor"],
            "detail": job["detail"],
            "progress": float(job["progress"] or 0),
            "gen": job["gen"],
            "error": job["error"] or "失敗",
        }
    return {
        "kind": job["kind"],
        "status": status,
        "actor": job["actor"],
        "detail": job["detail"],
        "progress": float(job["progress"] or 0),
        "gen": job["gen"],
        "error": "",
    }


def ensure_jobs(store: StoryStore) -> None:
    store.cx.executescript(JOBS_DDL)
    store.cx.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS jobs_one_active_per_story
           ON jobs (story_id) WHERE status IN ('queued', 'running')"""
    )
    store.cx.commit()


class Busy(Exception):
    pass


def _unique_violation(exc: BaseException) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    try:
        from psycopg.errors import UniqueViolation

        if isinstance(exc, UniqueViolation):
            return True
    except Exception:
        pass
    msg = str(exc).lower()
    return "unique" in msg or "jobs_one_active" in msg


def _clear_canon_activity(store: StoryStore, story_id: str) -> None:
    """Reset a stuck activity=thinking in the story's canon world after a job dies."""
    try:
        from playout.canon import World

        ref = store.canon_ref(story_id)
        if not store.canon_exists(story_id):
            return
        world = World(ref, database_url=store.database_url)
        try:
            current = world.meta("activity") or ""
            if current != "idle":
                world.set_activity("idle", error="worker heartbeat lost")
        finally:
            world.close()
    except Exception:
        pass


def _notify(store: StoryStore, job_id: str) -> None:
    if not store.database_url:
        return
    try:
        store.cx.execute("SELECT pg_notify('playout', ?)", (job_id,))
        store.cx.commit()
    except Exception:
        try:
            store.cx.rollback()
        except Exception:
            pass


def enqueue(
    store: StoryStore,
    story_id: str,
    kind: str,
    *,
    payload: dict[str, Any] | None = None,
    actor: str = "",
    detail: str = "",
    progress: float = 0.05,
) -> dict[str, Any]:
    expire_stale(store)
    job_id = str(uuid.uuid4())
    now = _now()
    blob = json.dumps(payload or {}, ensure_ascii=False)
    with store._lock:
        try:
            store.cx.execute(
                """INSERT INTO jobs
                   (id, story_id, kind, payload, status, actor, detail, progress,
                    error, gen, heartbeat_at, created_at, started_at, finished_at, locked_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job_id,
                    story_id,
                    kind,
                    blob,
                    "queued",
                    actor,
                    detail,
                    progress,
                    "",
                    1,
                    now,
                    now,
                    None,
                    None,
                    None,
                ),
            )
            store.cx.commit()
        except Exception as e:
            try:
                store.cx.rollback()
            except Exception:
                pass
            if _unique_violation(e):
                raise Busy("busy") from e
            raise
    _notify(store, job_id)
    job = get(store, job_id)
    assert job is not None
    return job


def get(store: StoryStore, job_id: str) -> dict[str, Any] | None:
    row = store.cx.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _row(row) if row else None


def active_job(store: StoryStore, story_id: str) -> dict[str, Any] | None:
    row = store.cx.execute(
        """SELECT * FROM jobs WHERE story_id=? AND status IN ('queued','running')
           ORDER BY created_at DESC LIMIT 1""",
        (story_id,),
    ).fetchone()
    return _row(row) if row else None


def latest_job(store: StoryStore, story_id: str) -> dict[str, Any] | None:
    row = store.cx.execute(
        "SELECT * FROM jobs WHERE story_id=? ORDER BY created_at DESC LIMIT 1",
        (story_id,),
    ).fetchone()
    return _row(row) if row else None


def agent_state(store: StoryStore, story_id: str) -> dict[str, Any]:
    return agent_from_job(latest_job(store, story_id))


def story_busy(store: StoryStore, story_id: str) -> bool:
    expire_stale(store)
    return active_job(store, story_id) is not None


def bump(
    store: StoryStore,
    job_id: str,
    *,
    detail: str | None = None,
    progress: float | None = None,
    actor: str | None = None,
    error: str | None = None,
) -> None:
    job = get(store, job_id)
    if not job:
        return
    gen = int(job["gen"] or 0) + 1
    store.cx.execute(
        """UPDATE jobs SET detail=?, progress=?, actor=?, error=?, gen=?, heartbeat_at=?
           WHERE id=?""",
        (
            job["detail"] if detail is None else detail,
            job["progress"] if progress is None else progress,
            job["actor"] if actor is None else actor,
            job["error"] if error is None else error,
            gen,
            _now(),
            job_id,
        ),
    )
    store.cx.commit()
    _notify(store, job_id)


def heartbeat(store: StoryStore, job_id: str) -> None:
    store.cx.execute(
        "UPDATE jobs SET heartbeat_at=? WHERE id=? AND status='running'",
        (_now(), job_id),
    )
    store.cx.commit()


def finish(
    store: StoryStore,
    job_id: str,
    *,
    status: str,
    error: str = "",
    detail: str | None = None,
) -> None:
    job = get(store, job_id)
    progress = 1.0 if status == "done" else float((job or {}).get("progress") or 0)
    now = _now()
    if detail is not None:
        store.cx.execute(
            """UPDATE jobs SET status=?, error=?, progress=?, detail=?, gen=gen+1,
               finished_at=?, heartbeat_at=? WHERE id=?""",
            (status, error, progress, detail, now, now, job_id),
        )
    else:
        store.cx.execute(
            """UPDATE jobs SET status=?, error=?, progress=?, gen=gen+1,
               finished_at=?, heartbeat_at=? WHERE id=?""",
            (status, error, progress, now, now, job_id),
        )
    store.cx.commit()
    _notify(store, job_id)


def expire_stale(store: StoryStore) -> None:
    cutoff = datetime.now(timezone.utc) - STALE_AFTER
    rows = list(
        store.cx.execute(
            "SELECT id, story_id, heartbeat_at FROM jobs WHERE status='running'"
        )
    )
    stale = []
    for r in rows:
        hb = _parse_ts(r["heartbeat_at"])
        if hb is None or hb < cutoff:
            stale.append({"id": r["id"], "story_id": r["story_id"]})
    for job in stale:
        store.cx.execute(
            """UPDATE jobs SET status='error', error=?, finished_at=?, gen=gen+1
               WHERE id=? AND status='running'""",
            ("worker heartbeat lost", _now(), job["id"]),
        )
    if stale:
        store.cx.commit()
        # Best-effort: reset the world's activity so the UI unlocks.
        for job in stale:
            _clear_canon_activity(store, job["story_id"])


def claim_one(store: StoryStore, worker_id: str) -> dict[str, Any] | None:
    expire_stale(store)
    now = _now()
    with store._lock:
        if store.database_url:
            row = store.cx.execute(
                """UPDATE jobs SET status='running', locked_by=?, started_at=?, heartbeat_at=?
                   WHERE id = (
                     SELECT id FROM jobs WHERE status='queued'
                     ORDER BY created_at ASC
                     FOR UPDATE SKIP LOCKED
                     LIMIT 1
                   )
                   RETURNING *""",
                (worker_id, now, now),
            ).fetchone()
            store.cx.commit()
            return _row(row) if row else None
        row = store.cx.execute(
            "SELECT id FROM jobs WHERE status='queued' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        store.cx.execute(
            """UPDATE jobs SET status='running', locked_by=?, started_at=?, heartbeat_at=?
               WHERE id=? AND status='queued'""",
            (worker_id, now, now, row["id"]),
        )
        store.cx.commit()
        return get(store, row["id"])


def worker_mode() -> str:
    raw = (os.getenv("PLAYOUT_WORKER") or "").strip().lower()
    if raw in ("inline", "external"):
        return raw
    return "external" if os.getenv("DATABASE_URL") or os.getenv("PLAYOUT_DATABASE_URL") else "inline"
