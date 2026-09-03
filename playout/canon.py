"""Append-only canon. Current actor/location rows are projections; the event tape is sealed."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS locations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    intact INTEGER NOT NULL DEFAULT 1,
    x REAL NOT NULL DEFAULT 0,
    y REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS edges (
    a TEXT NOT NULL,
    b TEXT NOT NULL,
    PRIMARY KEY (a, b)
);

CREATE TABLE IF NOT EXISTS actors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    voice TEXT NOT NULL,
    want TEXT NOT NULL,
    secret TEXT NOT NULL,
    constitution TEXT NOT NULL,
    location_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    mood TEXT NOT NULL,
    alive INTEGER NOT NULL DEFAULT 1,
    injured INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (location_id) REFERENCES locations(id)
);

CREATE TABLE IF NOT EXISTS objects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    location_id TEXT,
    holder_id TEXT,
    hidden INTEGER NOT NULL DEFAULT 0,
    destroyed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS relationships (
    a TEXT NOT NULL,
    b TEXT NOT NULL,
    trust INTEGER NOT NULL DEFAULT 0,
    resentment INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (a, b)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day INTEGER NOT NULL,
    scene INTEGER NOT NULL,
    kind TEXT NOT NULL,
    actor_id TEXT,
    target_id TEXT,
    summary TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS perceptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    actor_id TEXT NOT NULL,
    text TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES events(id)
);

CREATE TABLE IF NOT EXISTS diaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id TEXT NOT NULL,
    event_id INTEGER,
    day INTEGER NOT NULL,
    scene INTEGER NOT NULL,
    text TEXT NOT NULL,
    importance INTEGER NOT NULL DEFAULT 5
);

CREATE TABLE IF NOT EXISTS reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id TEXT NOT NULL,
    day INTEGER NOT NULL,
    scene INTEGER NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day INTEGER NOT NULL,
    pov TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '[]',
    cited_event_ids TEXT NOT NULL DEFAULT '[]',
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS steer_intents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    status TEXT NOT NULL,
    campaign TEXT NOT NULL DEFAULT '{}',
    created_day INTEGER NOT NULL,
    created_scene INTEGER NOT NULL
);
"""

TIME_LABELS = ["黎明", "上午", "正午", "午後", "黃昏", "夜"]


class CanonError(Exception):
    pass


class World:
    def __init__(self, db_path: str | Path, *, readonly: bool = False):
        self.db_path = str(Path(db_path).resolve())
        self.readonly = readonly
        self._lock = threading.RLock()
        if readonly:
            uri = Path(self.db_path).as_uri() + "?mode=ro"
            self.cx = sqlite3.connect(
                uri, uri=True, timeout=5.0, check_same_thread=False
            )
            self.cx.row_factory = sqlite3.Row
            self.cx.execute("PRAGMA query_only=ON")
            return
        self.cx = sqlite3.connect(self.db_path, check_same_thread=False, timeout=5.0)
        self.cx.row_factory = sqlite3.Row
        self.cx.executescript(SCHEMA)
        self.cx.execute(
            "CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'canon sealed'); END;"
        )
        self.cx.execute(
            "CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'canon sealed'); END;"
        )
        self.cx.execute(
            "CREATE TRIGGER IF NOT EXISTS diaries_no_update BEFORE UPDATE ON diaries BEGIN SELECT RAISE(ABORT, 'canon sealed'); END;"
        )
        self.cx.execute(
            "CREATE TRIGGER IF NOT EXISTS diaries_no_delete BEFORE DELETE ON diaries BEGIN SELECT RAISE(ABORT, 'canon sealed'); END;"
        )
        self.cx.execute(
            "CREATE TRIGGER IF NOT EXISTS chapters_no_update BEFORE UPDATE ON chapters BEGIN SELECT RAISE(ABORT, 'canon sealed'); END;"
        )
        self.cx.execute(
            "CREATE TRIGGER IF NOT EXISTS chapters_no_delete BEFORE DELETE ON chapters BEGIN SELECT RAISE(ABORT, 'canon sealed'); END;"
        )
        self.cx.execute(
            "CREATE TRIGGER IF NOT EXISTS perceptions_no_update BEFORE UPDATE ON perceptions BEGIN SELECT RAISE(ABORT, 'canon sealed'); END;"
        )
        self.cx.commit()

    def close(self) -> None:
        self.cx.close()

    def reader(self) -> "World":
        """Second WAL connection. Safe to snapshot while the writer is in OpenRouter."""
        return World(self.db_path, readonly=True)

    def set_activity(
        self,
        status: str,
        *,
        actor: str = "",
        detail: str = "",
        error: str | None = None,
    ) -> None:
        if self.readonly:
            raise CanonError("reader cannot write activity")
        gen = int(self.meta("activity_gen", "0") or 0) + 1
        self.set_meta("activity", status)
        self.set_meta("activity_actor", actor)
        self.set_meta("activity_detail", detail)
        self.set_meta("activity_gen", str(gen))
        if error is not None:
            self.set_meta("activity_error", error)
        self.cx.commit()

    def stream_cursor(self) -> tuple[Any, ...]:
        def _max(table: str) -> int:
            row = self.cx.execute(
                f"SELECT COALESCE(MAX(id), 0) AS m FROM {table}"
            ).fetchone()
            return int(row["m"])

        plan = self.get_day_plan() or {}
        return (
            _max("events"),
            _max("diaries"),
            _max("chapters"),
            int(self.meta("activity_gen", "0") or 0),
            self.meta("encounter") or "",
            int(plan.get("cursor") or 0),
            self.meta("activity") or "idle",
            self.meta("activity_detail") or "",
            self.meta("activity_error") or "",
        )

    def meta(self, key: str, default: str | None = None) -> str | None:
        row = self.cx.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.cx.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    @property
    def day(self) -> int:
        return int(self.meta("day", "1") or 1)

    @property
    def scene(self) -> int:
        return int(self.meta("scene", "0") or 0)

    @property
    def scenes_per_day(self) -> int:
        return int(self.meta("scenes_per_day", "6") or 6)

    @property
    def time_label(self) -> str:
        labels = json.loads(self.meta("time_labels", json.dumps(TIME_LABELS)) or "[]")
        n = max(len(labels), 1)
        return labels[self.scene % n]

    @property
    def day_run_multiplier(self) -> int:
        return int(self.meta("day_run_multiplier", "2") or 2)

    def get_day_plan(self) -> dict[str, Any] | None:
        raw = self.meta("day_plan")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set_day_plan(self, plan: dict[str, Any] | None) -> None:
        self.set_meta("day_plan", json.dumps(plan, ensure_ascii=False) if plan else "")
        self.cx.commit()

    def get_encounter(self) -> dict[str, Any] | None:
        raw = self.meta("encounter")
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if data else None

    def set_encounter(self, data: dict[str, Any] | None) -> None:
        self.set_meta(
            "encounter", json.dumps(data, ensure_ascii=False) if data else ""
        )
        self.cx.commit()

    @property
    def beat_label(self) -> str:
        plan = self.get_day_plan()
        if not plan:
            return f"第{self.day}日"
        total = len(plan.get("slots") or [])
        k = int(plan.get("cursor") or 0) + 1
        if total <= 0:
            return f"第{self.day}日"
        return f"第{self.day}日，第 {min(k, total)}/{total} 次"

    def bootstrap(self, scenario: dict[str, Any]) -> None:
        """Fresh world from scenario dict. Call on a new/empty database."""
        self.set_meta("title", scenario.get("title", "Untitled"))
        self.set_meta("worldview", scenario.get("worldview", ""))
        self.set_meta("day", "1")
        self.set_meta("scene", "0")
        self.set_meta("scenes_per_day", str(scenario.get("scenes_per_day", 6)))
        self.set_meta("max_days", str(scenario.get("days", 3)))
        self.set_meta("paused", "0")
        self.set_meta("clock", json.dumps(scenario.get("clock", {})))
        self.set_meta("weather", scenario.get("weather", "overcast, wind rising"))
        self.set_meta(
            "time_labels", json.dumps(scenario.get("time_labels", TIME_LABELS))
        )
        self.set_meta("idle_scenes", "0")
        self.set_meta("idle_days", "0")
        self.set_meta(
            "day_run_multiplier", str(scenario.get("day_run_multiplier", 2))
        )
        self.set_meta("day_plan", "")
        self.set_meta("encounter", "")
        self.set_meta("activity", "idle")
        self.set_meta("activity_actor", "")
        self.set_meta("activity_detail", "")
        self.set_meta("activity_gen", "0")
        self.set_meta("activity_error", "")

        for loc in scenario["locations"]:
            self.cx.execute(
                "INSERT INTO locations(id, name, description, intact, x, y) VALUES(?,?,?,?,?,?)",
                (
                    loc["id"],
                    loc["name"],
                    loc["description"],
                    1 if loc.get("intact", True) else 0,
                    loc.get("x", 0),
                    loc.get("y", 0),
                ),
            )
        for a, b in scenario.get("edges", []):
            self.cx.execute("INSERT OR IGNORE INTO edges(a, b) VALUES(?,?)", (a, b))
            self.cx.execute("INSERT OR IGNORE INTO edges(a, b) VALUES(?,?)", (b, a))
        for act in scenario["actors"]:
            self.cx.execute(
                """INSERT INTO actors(id, name, voice, want, secret, constitution, location_id, goal, mood, alive, injured)
                   VALUES(?,?,?,?,?,?,?,?,?,1,0)""",
                (
                    act["id"],
                    act["name"],
                    act["voice"],
                    act["want"],
                    act["secret"],
                    act["constitution"],
                    act["location"],
                    act.get("goal", act["want"]),
                    act.get("mood", "uneasy"),
                ),
            )
        for obj in scenario.get("objects", []):
            self.cx.execute(
                """INSERT INTO objects(id, name, description, location_id, holder_id, hidden, destroyed)
                   VALUES(?,?,?,?,?,?,0)""",
                (
                    obj["id"],
                    obj["name"],
                    obj["description"],
                    obj.get("location_id"),
                    obj.get("holder_id"),
                    1 if obj.get("hidden") else 0,
                ),
            )
        for rel in scenario.get("relationships", []):
            self.cx.execute(
                "INSERT INTO relationships(a, b, trust, resentment, notes) VALUES(?,?,?,?,?)",
                (
                    rel["a"],
                    rel["b"],
                    rel.get("trust", 0),
                    rel.get("resentment", 0),
                    rel.get("notes", ""),
                ),
            )
        self.cx.commit()
        for opening in scenario.get("opening_events", []):
            eid = self.append_event(
                kind=opening.get("kind", "world"),
                summary=opening["summary"],
                actor_id=opening.get("actor_id"),
                target_id=opening.get("target_id"),
                payload=opening.get("payload", {}),
            )
            who = opening.get("perceive", [a["id"] for a in scenario["actors"]])
            for actor_id in who:
                self.perceive(eid, actor_id, opening["summary"])
        self.cx.commit()

    def append_event(
        self,
        kind: str,
        summary: str,
        actor_id: str | None = None,
        target_id: str | None = None,
        payload: dict | None = None,
    ) -> int:
        cur = self.cx.execute(
            """INSERT INTO events(day, scene, kind, actor_id, target_id, summary, payload)
               VALUES(?,?,?,?,?,?,?)""",
            (
                self.day,
                self.scene,
                kind,
                actor_id,
                target_id,
                summary,
                json.dumps(payload or {}),
            ),
        )
        self.cx.commit()
        return int(cur.lastrowid)

    def perceive(self, event_id: int, actor_id: str, text: str) -> None:
        self.cx.execute(
            "INSERT INTO perceptions(event_id, actor_id, text) VALUES(?,?,?)",
            (event_id, actor_id, text),
        )
        self.cx.commit()

    def write_diary(
        self, actor_id: str, text: str, importance: int = 5, event_id: int | None = None
    ) -> None:
        self.cx.execute(
            "INSERT INTO diaries(actor_id, event_id, day, scene, text, importance) VALUES(?,?,?,?,?,?)",
            (actor_id, event_id, self.day, self.scene, text, importance),
        )
        self.cx.commit()

    def write_reflection(self, actor_id: str, text: str) -> None:
        self.cx.execute(
            "INSERT INTO reflections(actor_id, day, scene, text) VALUES(?,?,?,?)",
            (actor_id, self.day, self.scene, text),
        )
        self.cx.commit()

    def write_chapter(
        self, day: int, pov: str, text: str, tags: list[str], cited: list[int]
    ) -> int:
        cur = self.cx.execute(
            "INSERT INTO chapters(day, pov, tags, cited_event_ids, text) VALUES(?,?,?,?,?)",
            (day, pov, json.dumps(tags), json.dumps(cited), text),
        )
        self.cx.commit()
        return int(cur.lastrowid)

    def actor(self, actor_id: str) -> sqlite3.Row:
        row = self.cx.execute("SELECT * FROM actors WHERE id=?", (actor_id,)).fetchone()
        if not row:
            raise CanonError(f"unknown actor {actor_id}")
        return row

    def location(self, loc_id: str) -> sqlite3.Row:
        row = self.cx.execute(
            "SELECT * FROM locations WHERE id=?", (loc_id,)
        ).fetchone()
        if not row:
            raise CanonError(f"unknown location {loc_id}")
        return row

    def living_actors(self) -> list[sqlite3.Row]:
        return list(self.cx.execute("SELECT * FROM actors WHERE alive=1 ORDER BY id"))

    def actors_at(self, loc_id: str, alive_only: bool = True) -> list[sqlite3.Row]:
        q = "SELECT * FROM actors WHERE location_id=?"
        if alive_only:
            q += " AND alive=1"
        return list(self.cx.execute(q + " ORDER BY id", (loc_id,)))

    def adjacent(self, loc_id: str) -> list[str]:
        return [
            r["b"] for r in self.cx.execute("SELECT b FROM edges WHERE a=?", (loc_id,))
        ]

    def exits(self, loc_id: str) -> list["ConnectedExit"]:
        """Intact neighbors — the only legal voluntary/forced hop destinations."""
        from playout.models import ConnectedExit

        out: list[ConnectedExit] = []
        for dest_id in self.adjacent(loc_id):
            dest = self.location(dest_id)
            if dest["intact"]:
                out.append(
                    ConnectedExit(id=dest["id"], name=dest["name"], intact=True)
                )
        return out

    def node(self, loc_id: str) -> "LocationNode":
        from playout.models import ConnectedExit, LocationNode, NodeObject, NodePerson

        loc = self.location(loc_id)
        connected: list[ConnectedExit] = []
        for dest_id in self.adjacent(loc_id):
            dest = self.location(dest_id)
            connected.append(
                ConnectedExit(
                    id=dest["id"],
                    name=dest["name"],
                    intact=bool(dest["intact"]),
                )
            )
        present = [
            NodePerson(
                id=a["id"],
                name=a["name"],
                injured=bool(a["injured"]),
                alive=bool(a["alive"]),
            )
            for a in self.actors_at(loc_id, alive_only=False)
        ]
        objects = [
            NodeObject(id=o["id"], name=o["name"], description=o["description"])
            for o in self.visible_objects(loc_id)
        ]
        return LocationNode(
            id=loc["id"],
            name=loc["name"],
            description=loc["description"],
            intact=bool(loc["intact"]),
            x=float(loc["x"] or 0),
            y=float(loc["y"] or 0),
            connected=connected,
            present=present,
            visible_objects=objects,
        )

    def atmosphere(self) -> "WorldAtmosphere":
        from playout.models import WorldAtmosphere

        return WorldAtmosphere(
            title=self.meta("title") or "",
            worldview=self.meta("worldview") or "",
            day=self.day,
            beat=self.beat_label,
            weather=self.meta("weather") or "",
            clock=self.meta("clock") or "",
        )

    def event_payload(self, event_id: int) -> dict[str, Any]:
        row = self.cx.execute(
            "SELECT payload FROM events WHERE id=?", (event_id,)
        ).fetchone()
        if not row:
            return {}
        try:
            data = json.loads(row["payload"] or "{}")
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def visible_objects(
        self, loc_id: str, include_hidden: bool = False
    ) -> list[sqlite3.Row]:
        q = "SELECT * FROM objects WHERE location_id=? AND destroyed=0 AND holder_id IS NULL"
        if not include_hidden:
            q += " AND hidden=0"
        return list(self.cx.execute(q, (loc_id,)))

    def inventory(self, actor_id: str) -> list[sqlite3.Row]:
        return list(
            self.cx.execute(
                "SELECT * FROM objects WHERE holder_id=? AND destroyed=0", (actor_id,)
            )
        )

    def object(self, object_id: str) -> sqlite3.Row | None:
        return self.cx.execute(
            "SELECT * FROM objects WHERE id=?", (object_id,)
        ).fetchone()

    def relationship(self, a: str, b: str) -> sqlite3.Row | None:
        return self.cx.execute(
            "SELECT * FROM relationships WHERE a=? AND b=?", (a, b)
        ).fetchone()

    def bump_relationship(
        self,
        a: str,
        b: str,
        trust: int = 0,
        resentment: int = 0,
        note: str | None = None,
    ) -> None:
        row = self.relationship(a, b)
        if not row:
            self.cx.execute(
                "INSERT INTO relationships(a, b, trust, resentment, notes) VALUES(?,?,?,?,?)",
                (a, b, trust, resentment, note or ""),
            )
        else:
            notes = row["notes"]
            if note:
                notes = (notes + " | " + note).strip(" |")
            self.cx.execute(
                "UPDATE relationships SET trust=?, resentment=?, notes=? WHERE a=? AND b=?",
                (
                    max(-10, min(10, row["trust"] + trust)),
                    max(-10, min(10, row["resentment"] + resentment)),
                    notes,
                    a,
                    b,
                ),
            )
        self.cx.commit()

    def set_actor_location(self, actor_id: str, loc_id: str) -> None:
        self.cx.execute(
            "UPDATE actors SET location_id=? WHERE id=?", (loc_id, actor_id)
        )
        self.cx.commit()

    def set_actor_goal(self, actor_id: str, goal: str) -> None:
        self.cx.execute("UPDATE actors SET goal=? WHERE id=?", (goal, actor_id))
        self.cx.commit()

    def set_actor_mood(self, actor_id: str, mood: str) -> None:
        self.cx.execute("UPDATE actors SET mood=? WHERE id=?", (mood, actor_id))
        self.cx.commit()

    def set_injured(self, actor_id: str, injured: bool) -> None:
        self.cx.execute(
            "UPDATE actors SET injured=? WHERE id=?", (1 if injured else 0, actor_id)
        )
        self.cx.commit()

    def set_alive(self, actor_id: str, alive: bool) -> None:
        self.cx.execute(
            "UPDATE actors SET alive=? WHERE id=?", (1 if alive else 0, actor_id)
        )
        self.cx.commit()

    def perceptions_for(self, actor_id: str, limit: int = 30) -> list[sqlite3.Row]:
        return list(
            self.cx.execute(
                """SELECT p.text, e.day, e.scene, e.kind, e.id as event_id
                   FROM perceptions p JOIN events e ON e.id=p.event_id
                   WHERE p.actor_id=? ORDER BY p.id DESC LIMIT ?""",
                (actor_id, limit),
            )
        )

    def diary_for(self, actor_id: str, limit: int = 40) -> list[sqlite3.Row]:
        return list(
            self.cx.execute(
                "SELECT * FROM diaries WHERE actor_id=? ORDER BY id DESC LIMIT ?",
                (actor_id, limit),
            )
        )

    def reflections_for(self, actor_id: str, limit: int = 8) -> list[sqlite3.Row]:
        return list(
            self.cx.execute(
                "SELECT * FROM reflections WHERE actor_id=? ORDER BY id DESC LIMIT ?",
                (actor_id, limit),
            )
        )

    def events_since(self, after_id: int = 0) -> list[sqlite3.Row]:
        return list(
            self.cx.execute("SELECT * FROM events WHERE id>? ORDER BY id", (after_id,))
        )

    def events_for_day(self, day: int) -> list[sqlite3.Row]:
        return list(
            self.cx.execute("SELECT * FROM events WHERE day=? ORDER BY id", (day,))
        )

    def all_events(self) -> list[sqlite3.Row]:
        return list(self.cx.execute("SELECT * FROM events ORDER BY id"))

    def death_events(self) -> list[sqlite3.Row]:
        return list(
            self.cx.execute(
                "SELECT * FROM events WHERE kind IN ('kill','death','world_kill') ORDER BY id"
            )
        )

    def advance_scene(self) -> dict[str, Any]:
        scene = self.scene + 1
        day = self.day
        rolled = False
        if scene >= self.scenes_per_day:
            scene = 0
            day += 1
            rolled = True
        self.set_meta("scene", str(scene))
        self.set_meta("day", str(day))
        self.cx.commit()
        return {
            "day": day,
            "scene": scene,
            "rolled_day": rolled,
            "previous_day": day - 1 if rolled else day,
        }

    def snapshot(self) -> dict[str, Any]:
        locs = []
        for loc in self.cx.execute("SELECT * FROM locations").fetchall():
            people = [
                {"id": a["id"], "name": a["name"], "alive": bool(a["alive"])}
                for a in self.cx.execute(
                    "SELECT * FROM actors WHERE location_id=?", (loc["id"],)
                ).fetchall()
            ]
            objs = [
                {"id": o["id"], "name": o["name"], "hidden": bool(o["hidden"])}
                for o in self.visible_objects(loc["id"], include_hidden=False)
            ]
            locs.append({
                "id": loc["id"],
                "name": loc["name"],
                "description": loc["description"],
                "intact": bool(loc["intact"]),
                "x": loc["x"],
                "y": loc["y"],
                "actors": people,
                "objects": objs,
            })
        actors = []
        for a in self.cx.execute("SELECT * FROM actors ORDER BY id").fetchall():
            inv = [{"id": o["id"], "name": o["name"]} for o in self.inventory(a["id"])]
            actors.append({
                "id": a["id"],
                "name": a["name"],
                "voice": a["voice"],
                "want": a["want"],
                "secret": a["secret"],
                "constitution": a["constitution"],
                "location_id": a["location_id"],
                "goal": a["goal"],
                "mood": a["mood"],
                "alive": bool(a["alive"]),
                "injured": bool(a["injured"]),
                "inventory": inv,
            })
        events = [
            {
                "id": e["id"],
                "day": e["day"],
                "scene": e["scene"],
                "kind": e["kind"],
                "actor_id": e["actor_id"],
                "target_id": e["target_id"],
                "summary": e["summary"],
            }
            for e in self.cx.execute("SELECT * FROM events ORDER BY id DESC LIMIT 120")
        ]
        diaries: dict[str, list] = {}
        for a in actors:
            diaries[a["id"]] = [
                {
                    "day": d["day"],
                    "scene": d["scene"],
                    "text": d["text"],
                    "importance": d["importance"],
                }
                for d in self.cx.execute(
                    "SELECT * FROM diaries WHERE actor_id=? ORDER BY id DESC LIMIT 20",
                    (a["id"],),
                )
            ]
        chapters = [
            {
                "id": c["id"],
                "day": c["day"],
                "pov": c["pov"],
                "tags": json.loads(c["tags"]),
                "cited_event_ids": json.loads(c["cited_event_ids"]),
                "text": c["text"],
            }
            for c in self.cx.execute("SELECT * FROM chapters ORDER BY id")
        ]
        intents = [
            {
                "id": i["id"],
                "text": i["text"],
                "status": i["status"],
                "campaign": json.loads(i["campaign"]),
                "created_day": i["created_day"],
                "created_scene": i["created_scene"],
            }
            for i in self.cx.execute("SELECT * FROM steer_intents ORDER BY id")
        ]
        edges = [
            {"a": e["a"], "b": e["b"]} for e in self.cx.execute("SELECT * FROM edges")
        ]
        return {
            "title": self.meta("title"),
            "worldview": self.meta("worldview"),
            "day": self.day,
            "scene": self.scene,
            "time_label": self.beat_label,
            "scenes_per_day": self.scenes_per_day,
            "day_plan": self.get_day_plan(),
            "day_run_multiplier": self.day_run_multiplier,
            "encounter": self.get_encounter(),
            "max_days": int(self.meta("max_days", "3") or 3),
            "weather": self.meta("weather"),
            "clock": json.loads(self.meta("clock") or "{}"),
            "paused": self.meta("paused") == "1",
            "llm_mode": self.meta("llm_mode", "mock"),
            "llm_model": self.meta("llm_model", ""),
            "activity": self.meta("activity", "idle") or "idle",
            "activity_actor": self.meta("activity_actor", "") or "",
            "activity_detail": self.meta("activity_detail", "") or "",
            "activity_gen": int(self.meta("activity_gen", "0") or 0),
            "activity_error": self.meta("activity_error", "") or "",
            "locations": locs,
            "edges": edges,
            "actors": actors,
            "events": list(reversed(events)),
            "diaries": diaries,
            "chapters": chapters,
            "intents": intents,
        }


def unlink_db(db_path: str | Path) -> None:
    path = Path(db_path)
    if path.exists():
        path.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            p.unlink()


def world_from_setup(db_path: str | Path, setup: dict[str, Any]) -> World:
    unlink_db(db_path)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    world = World(db_path)
    world.bootstrap(setup)
    return world


def world_from_scenario(db_path: str | Path, scenario_path: str | Path) -> World:
    scenario = json.loads(Path(scenario_path).read_text())
    return world_from_setup(db_path, scenario)
