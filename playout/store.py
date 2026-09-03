"""Story catalog. Separate from sealed canon (SQLite files or Postgres schemas).

unseal() is temporary scaffolding: drop canon, return the row to draft so
the owner can edit setup again. Remove this method (and its HTTP route)
when live stories become irreplaceable.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playout import sql as dbsql
from playout.canon import World, unlink_db, world_from_setup
from playout.models import StorySetup, empty_setup

HARBORS_END = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"

CATALOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    status TEXT NOT NULL,
    setup_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class StoreError(Exception):
    pass


class NotFound(StoreError):
    pass


class SealedError(StoreError):
    """Setup cannot change while the story is live."""


class AlreadyLive(StoreError):
    pass


class AlreadyDraft(StoreError):
    pass


class SlugTaken(StoreError):
    pass


@dataclass
class StoryRecord:
    id: str
    slug: str
    title: str
    owner_id: str
    status: str
    setup_json: str
    created_at: str
    updated_at: str

    def setup(self) -> dict[str, Any]:
        return json.loads(self.setup_json)

    @property
    def editable(self) -> bool:
        return self.status == "draft"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slugify(title: str) -> str:
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text


def _row(r: Any) -> StoryRecord:
    return StoryRecord(
        id=r["id"],
        slug=r["slug"],
        title=r["title"],
        owner_id=r["owner_id"],
        status=r["status"],
        setup_json=r["setup_json"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


class StoryStore:
    def __init__(
        self,
        catalog_path: str | Path,
        stories_dir: str | Path,
        *,
        database_url: str | None = None,
    ):
        self.catalog_path = Path(catalog_path)
        self.stories_dir = Path(stories_dir)
        self.database_url = database_url
        self._lock = threading.RLock()
        if self.database_url:
            self.cx = dbsql.connect_postgres(
                schema="public", url=self.database_url
            )
            self.cx.execute(CATALOG_SCHEMA)
            self.cx.commit()
            return
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self.stories_dir.mkdir(parents=True, exist_ok=True)
        self.cx = sqlite3.connect(
            str(self.catalog_path), check_same_thread=False, timeout=5.0
        )
        self.cx.row_factory = sqlite3.Row
        self.cx.executescript(CATALOG_SCHEMA)
        self.cx.commit()

    def close(self) -> None:
        self.cx.close()

    def canon_path(self, story_id: str) -> Path:
        return self.stories_dir / f"{story_id}.db"

    def canon_ref(self, story_id: str) -> str:
        if self.database_url:
            return dbsql.story_source(story_id)
        return str(self.canon_path(story_id))

    def canon_exists(self, story_id: str) -> bool:
        if self.database_url:
            return dbsql.schema_exists(story_id, url=self.database_url)
        return self.canon_path(story_id).exists()

    def get(self, ref: str) -> StoryRecord | None:
        row = self.cx.execute(
            "SELECT * FROM stories WHERE id=? OR slug=?", (ref, ref)
        ).fetchone()
        return _row(row) if row else None

    def require(self, ref: str) -> StoryRecord:
        rec = self.get(ref)
        if not rec:
            raise NotFound(ref)
        return rec

    def list(self) -> list[StoryRecord]:
        return [
            _row(r)
            for r in self.cx.execute(
                "SELECT * FROM stories ORDER BY created_at ASC"
            )
        ]

    def _unique_slug(self, base: str, *, exclude_id: str | None = None) -> str:
        slug = base if SLUG_RE.match(base) else ""
        if not slug:
            slug = "story"
        n = 0
        while True:
            candidate = slug if n == 0 else f"{slug}-{n + 1}"
            row = self.cx.execute(
                "SELECT id FROM stories WHERE slug=?", (candidate,)
            ).fetchone()
            if not row or row["id"] == exclude_id:
                return candidate
            n += 1
            if n > 200:
                return f"{slug}-{uuid.uuid4().hex[:8]}"

    def create(
        self,
        owner_id: str,
        setup: StorySetup,
        *,
        slug: str | None = None,
        status: str = "draft",
    ) -> StoryRecord:
        with self._lock:
            sid = str(uuid.uuid4())
            wanted = slug or _slugify(setup.title) or f"story-{sid[:8]}"
            unique = self._unique_slug(wanted)
            now = _now()
            payload = json.dumps(setup.model_dump(mode="json"), ensure_ascii=False)
            self.cx.execute(
                """INSERT INTO stories
                   (id, slug, title, owner_id, status, setup_json, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    sid,
                    unique,
                    setup.title,
                    owner_id,
                    status,
                    payload,
                    now,
                    now,
                ),
            )
            self.cx.commit()
            return self.require(sid)

    def duplicate(self, ref: str, owner_id: str) -> StoryRecord:
        src = self.require(ref)
        setup = StorySetup.model_validate(src.setup())
        setup.title = f"{setup.title}（副本）"
        base = f"{src.slug}-copy"
        return self.create(owner_id, setup, slug=base, status="draft")

    def update_setup(
        self,
        ref: str,
        *,
        setup: StorySetup | None = None,
        title: str | None = None,
        slug: str | None = None,
    ) -> StoryRecord:
        with self._lock:
            rec = self.require(ref)
            if rec.status != "draft":
                raise SealedError("sealed")
            current = StorySetup.model_validate(rec.setup())
            if setup is not None:
                current = setup
            if title is not None:
                current.title = title
            payload = json.dumps(current.model_dump(mode="json"), ensure_ascii=False)
            new_title = current.title
            new_slug = rec.slug
            if slug is not None:
                wanted = slug.strip().lower()
                if not SLUG_RE.match(wanted):
                    raise StoreError("invalid slug")
                taken = self.cx.execute(
                    "SELECT id FROM stories WHERE slug=? AND id!=?",
                    (wanted, rec.id),
                ).fetchone()
                if taken:
                    raise SlugTaken(wanted)
                new_slug = wanted
            self.cx.execute(
                """UPDATE stories SET title=?, slug=?, setup_json=?, updated_at=?
                   WHERE id=?""",
                (new_title, new_slug, payload, _now(), rec.id),
            )
            self.cx.commit()
            return self.require(rec.id)

    def set_status(self, ref: str, status: str) -> StoryRecord:
        with self._lock:
            rec = self.require(ref)
            self.cx.execute(
                "UPDATE stories SET status=?, updated_at=? WHERE id=?",
                (status, _now(), rec.id),
            )
            self.cx.commit()
            return self.require(rec.id)

    def mark_live(self, ref: str) -> StoryRecord:
        rec = self.require(ref)
        if rec.status == "live":
            raise AlreadyLive("already live")
        return self.set_status(rec.id, "live")

    def unseal(self, ref: str) -> StoryRecord:
        """TEMPORARY: wipe canon and return to draft so setup can be edited.

        Delete this method when stories become unique and irreplaceable.
        """
        with self._lock:
            rec = self.require(ref)
            if rec.status != "live":
                raise AlreadyDraft("already draft")
            unlink_db(self.canon_ref(rec.id), database_url=self.database_url)
            self.cx.execute(
                "UPDATE stories SET status=?, updated_at=? WHERE id=?",
                ("draft", _now(), rec.id),
            )
            self.cx.commit()
            return self.require(rec.id)

    def peek_day(self, rec: StoryRecord) -> int | None:
        if rec.status != "live":
            return None
        if not self.canon_exists(rec.id):
            return None
        world = World(
            self.canon_ref(rec.id),
            readonly=True,
            database_url=self.database_url,
        )
        try:
            return world.day
        except Exception:
            return None
        finally:
            world.close()

    def seed_harbors_end(self, owner_id: str) -> StoryRecord | None:
        """Insert 港尾 as the first live story when the catalog is empty."""
        with self._lock:
            n = self.cx.execute("SELECT COUNT(*) c FROM stories").fetchone()["c"]
            if n:
                return None
        raw = json.loads(HARBORS_END.read_text(encoding="utf-8"))
        setup = StorySetup.model_validate(raw)
        rec = self.create(owner_id, setup, slug="harbors-end", status="draft")
        world = world_from_setup(
            self.canon_ref(rec.id),
            setup.model_dump(mode="json"),
            database_url=self.database_url,
        )
        world.close()
        return self.mark_live(rec.id)


def default_setup() -> StorySetup:
    return empty_setup()
