"""Postgres-backed catalog + canon. Skipped unless PLAYOUT_TEST_DATABASE_URL is set."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from playout.canon import world_from_scenario
from playout.models import empty_setup
from playout.sql import story_source
from playout.store import StoryStore

SCENARIO = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"

pytestmark = pytest.mark.skipif(
    not os.getenv("PLAYOUT_TEST_DATABASE_URL"),
    reason="PLAYOUT_TEST_DATABASE_URL not set",
)


@pytest.fixture
def pg_url():
    return os.environ["PLAYOUT_TEST_DATABASE_URL"]


def test_postgres_catalog_and_two_stories(tmp_path, pg_url):
    store = StoryStore(
        tmp_path / "unused.db", tmp_path / "stories", database_url=pg_url
    )
    token = os.urandom(3).hex()
    a = store.create("dev-owner", empty_setup("甲"), slug=f"jia-pg-{token}")
    b = store.create("dev-owner", empty_setup("乙"), slug=f"yi-pg-{token}")
    from playout.runtime import StoryRuntime

    rt = StoryRuntime(store)
    rt.start(a)
    rt.start(store.require(b.id))
    sa = rt.snapshot(store.require(a.id))
    sb = rt.snapshot(store.require(b.id))
    assert sa["title"] == "甲"
    assert sb["title"] == "乙"
    rt.unseal(store.require(a.id))
    assert store.require(a.id).status == "draft"
    rt.close()
    store.close()


def test_postgres_canon_seals_events(pg_url):
    ref = story_source("pg-seal-test")
    w = world_from_scenario(ref, SCENARIO, database_url=pg_url)
    try:
        eid = w.append_event("world", "A gull screams.")
        with pytest.raises(Exception):
            w.cx.execute("UPDATE events SET summary='nope' WHERE id=?", (eid,))
            w.cx.commit()
        w.cx.rollback()
        row = w.cx.execute(
            "SELECT summary FROM events WHERE id=?", (eid,)
        ).fetchone()
        assert row["summary"] == "A gull screams."
    finally:
        w.close()
        from playout.canon import unlink_db

        unlink_db(ref, database_url=pg_url)
