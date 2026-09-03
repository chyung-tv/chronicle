"""In-memory Simulation registry keyed by story id."""

from __future__ import annotations

import threading
from typing import Any

from playout.loop import Simulation
from playout.store import AlreadyDraft, AlreadyLive, StoryRecord, StoryStore


class StoryRuntime:
    def __init__(self, store: StoryStore):
        self.store = store
        self._sims: dict[str, Simulation] = {}
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            for sim in self._sims.values():
                try:
                    sim.close()
                except Exception:
                    pass
            self._sims.clear()

    def close_one(self, story_id: str) -> None:
        with self._lock:
            sim = self._sims.pop(story_id, None)
            if sim is not None:
                try:
                    sim.close()
                except Exception:
                    pass

    def get(self, rec: StoryRecord) -> Simulation:
        if rec.status != "live":
            raise AlreadyDraft("story is not live")
        with self._lock:
            sim = self._sims.get(rec.id)
            if sim is not None:
                return sim
            path = self.store.canon_ref(rec.id)
            sim = Simulation.open_existing(str(path), database_url=self.store.database_url)
            self._sims[rec.id] = sim
            return sim

    def start(self, rec: StoryRecord) -> Simulation:
        if rec.status == "live":
            raise AlreadyLive("already live")
        with self._lock:
            self.close_one(rec.id)
            path = self.store.canon_ref(rec.id)
            sim = Simulation.create_from_setup(
                str(path), rec.setup(), database_url=self.store.database_url
            )
            self.store.mark_live(rec.id)
            self._sims[rec.id] = sim
            return sim

    def unseal(self, rec: StoryRecord) -> StoryRecord:
        """TEMPORARY: see StoryStore.unseal."""
        with self._lock:
            sim = self._sims.get(rec.id)
            if sim is not None:
                activity = sim.world.meta("activity", "idle") or "idle"
                if activity != "idle":
                    raise RuntimeError("busy")
            self.close_one(rec.id)
            return self.store.unseal(rec.id)

    def snapshot(self, rec: StoryRecord) -> dict[str, Any]:
        return self.get(rec).reader.snapshot()
