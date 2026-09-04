from pathlib import Path
import time

from fastapi.testclient import TestClient

from playout.loop import Simulation
from playout.models import ActorSketch, StorySketch, empty_setup, empty_sketch
from playout.wizard import mock_enrich, stitch
import playout.app as appmod


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYOUT_CATALOG", str(tmp_path / "catalog.db"))
    monkeypatch.setenv("PLAYOUT_STORIES_DIR", str(tmp_path / "stories"))
    monkeypatch.setenv("PLAYOUT_DEV_USER_ID", "dev-owner")
    monkeypatch.setenv("PLAYOUT_LLM_MODE", "mock")
    appmod.close_runtime()


def test_mock_enrich_preserves_knobs_and_coords():
    sketch = StorySketch(
        title="小鎮",
        worldview="無神異。",
        opening_situation="雨。",
        opening_events="有人失蹤。",
        turns_per_day_max=6,
        locations=[
            {"id": "hall", "name": "廳", "note": "空屋子", "x": 100, "y": 80},
            {"id": "yard", "name": "院", "note": "泥", "x": 220, "y": 160},
        ],
        edges=[("hall", "yard")],
        actors=[
            ActorSketch(id="ann", name="安", note="聰明漂亮的女孩", location="hall"),
            ActorSketch(id="ben", name="本", note="欠債", location="yard"),
        ],
    )
    setup = mock_enrich(sketch)
    assert setup.title == "小鎮"
    assert setup.turns_per_day_min == 2
    assert setup.turns_per_day_max == 6
    assert [loc.id for loc in setup.locations] == ["hall", "yard"]
    assert (setup.locations[0].x, setup.locations[0].y) == (100, 80)
    assert setup.edges == [("hall", "yard")]
    assert [a.id for a in setup.actors] == ["ann", "ben"]
    assert "聰明漂亮的女孩" in setup.actors[0].want
    blob = setup.model_dump_json()
    assert "颱風" not in blob
    assert "舢板" not in blob
    assert "關瑪" not in blob


def test_generic_idle_pressure_is_not_harbors():
    setup = empty_setup("別處")
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        sim = Simulation.create_from_setup(str(Path(d) / "g.db"), setup.model_dump(mode="json"))
        text = sim._pressure_text()
        assert "颱風" not in text
        assert "舢板" not in text
        assert "關瑪" not in text
        sim.close()


def test_actor_cap():
    sketch = empty_sketch("眾")
    extra = [
        ActorSketch(id=f"actor{i}", name=f"人{i}", note="", location="place")
        for i in range(2, 10)
    ]
    try:
        StorySketch(
            title="眾",
            locations=sketch.locations,
            actors=[sketch.actors[0], *extra],
        )
        raise AssertionError("expected cap")
    except Exception as e:
        assert "8" in str(e)


def test_location_cap():
    sketch = empty_sketch("廣")
    extra = [
        {"id": f"loc{i}", "name": f"處{i}", "note": "", "x": 0, "y": 0}
        for i in range(2, 10)
    ]
    try:
        StorySketch(
            title="廣",
            locations=[sketch.locations[0], *extra],
            actors=sketch.actors,
        )
        raise AssertionError("expected cap")
    except Exception as e:
        assert "8" in str(e)


def test_wizard_endpoint_overwrites_setup(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    with TestClient(appmod.app) as client:
        rec = client.post("/api/stories", json={"title": "新稿"}).json()
        sid = rec["id"]
        sketch = rec["sketch"]
        sketch["actors"][0]["note"] = "聰明漂亮的女孩"
        patched = client.patch(f"/api/stories/{sid}", json={"sketch": sketch})
        assert patched.status_code == 200
        wiz = client.post(f"/api/stories/{sid}/wizard")
        assert wiz.status_code == 200
        assert wiz.json() == {"accepted": True}
        body = None
        for _ in range(80):
            body = client.get(f"/api/stories/{sid}").json()
            st = (body.get("agent") or {}).get("status")
            if st in ("done", "error", "idle") and st != "queued":
                if st != "running":
                    break
            time.sleep(0.1)
        assert body is not None
        assert body["agent"]["status"] in ("done", "idle")
        assert body["setup"]["actors"][0]["want"]
        assert "聰明漂亮的女孩" in body["setup"]["actors"][0]["want"]
        live = next(s for s in client.get("/api/stories").json() if s["slug"] == "harbors-end")
        sealed = client.post(f"/api/stories/{live['id']}/wizard")
        assert sealed.status_code == 409
    appmod.close_runtime()


def test_wizard_busy_without_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYOUT_WORKER", "external")
    _env(tmp_path, monkeypatch)
    with TestClient(appmod.app) as client:
        rec = client.post("/api/stories", json={"title": "新稿"}).json()
        sid = rec["id"]
        first = client.post(f"/api/stories/{sid}/wizard")
        assert first.status_code == 200
        second = client.post(f"/api/stories/{sid}/wizard")
        assert second.status_code == 409
    appmod.close_runtime()


def test_stitch_appends_extra_actors_and_locations():
    sketch = empty_sketch("甲")
    from playout.models import ActorSetup, LocationSetup

    drafted = empty_setup("甲")
    drafted = drafted.model_copy(
        update={
            "locations": [
                drafted.locations[0],
                LocationSetup(
                    id="side",
                    name="側巷",
                    description="一條窄巷。",
                    x=320,
                    y=200,
                ),
            ],
            "actors": [
                drafted.actors[0],
                ActorSetup(
                    id="intruder",
                    name="闖入者",
                    location="side",
                    voice="x",
                    want="x",
                    constitution="x",
                ),
            ],
        }
    )
    out = stitch(sketch, drafted)
    assert [a.id for a in out.actors] == ["someone", "intruder"]
    assert [loc.id for loc in out.locations] == ["place", "side"]
    assert any(set(e) == {"place", "side"} for e in out.edges)


def test_coerce_rewrites_illegal_object_ids():
    from playout.wizard import _coerce_draft

    sketch = empty_sketch("甲")
    data = _coerce_draft(
        {"objects": [{"id": "信件", "name": "信", "description": "一封信"}]},
        sketch,
    )
    oid = data["objects"][0]["id"]
    assert oid.isascii()
    assert oid[0].islower()
