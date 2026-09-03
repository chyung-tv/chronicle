from pathlib import Path

from fastapi.testclient import TestClient

from playout.models import parse_story_pack, empty_setup
from playout.store import StoryStore
import playout.app as appmod
import json

HARBORS = Path(__file__).resolve().parent.parent / "scenarios" / "harbors_end.json"


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYOUT_CATALOG", str(tmp_path / "catalog.db"))
    monkeypatch.setenv("PLAYOUT_STORIES_DIR", str(tmp_path / "stories"))
    monkeypatch.setenv("PLAYOUT_DEV_USER_ID", "dev-owner")
    appmod.close_runtime()


def _client(tmp_path, monkeypatch) -> TestClient:
    _env(tmp_path, monkeypatch)
    return TestClient(appmod.app)


def test_harbors_end_setup_validates():
    raw = json.loads(HARBORS.read_text(encoding="utf-8"))
    sketch, setup = parse_story_pack(raw)
    assert setup.title == "港尾"
    assert sketch.title == "港尾"
    assert len(setup.actors) == 4
    assert setup.turns_per_day_min == 4
    assert setup.turns_per_day_max == 8
    assert isinstance(setup.opening_events, str)
    assert "storm_in_days" not in setup.model_dump()


def test_me_returns_dev_user(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        r = client.get("/api/me")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == "dev-owner"
        assert body["name"]
        assert "playout_user=" in r.headers.get("set-cookie", "")
    appmod.close_runtime()
    with _client(tmp_path, monkeypatch) as client:
        stories = client.get("/api/stories").json()
        assert len(stories) == 1
        s = stories[0]
        assert s["slug"] == "harbors-end"
        assert s["title"] == "港尾"
        assert s["status"] == "live"
        assert s["is_owner"] is True
        snap = client.get(f"/api/stories/{s['id']}/state").json()
        assert snap["title"] == "港尾"
        assert len(snap["actors"]) == 4
    appmod.close_runtime()


def test_create_second_story_isolated(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        created = client.post("/api/stories", json={"title": "別港"}).json()
        assert created["status"] == "draft"
        assert created["editable"] is True
        assert created["title"] == "別港"
        stories = client.get("/api/stories").json()
        assert len(stories) == 2
        ids = {s["id"] for s in stories}
        assert created["id"] in ids
        live = next(s for s in stories if s["slug"] == "harbors-end")
        snap = client.get(f"/api/stories/{live['id']}/state").json()
        assert snap["title"] == "港尾"
        missing = client.get(f"/api/stories/{created['id']}/state")
        assert missing.status_code == 409
    appmod.close_runtime()


def test_two_runtimes_do_not_share_canon(tmp_path, monkeypatch):
    store = StoryStore(tmp_path / "c.db", tmp_path / "stories")
    a = store.create("dev-owner", empty_setup("甲"), slug="jia")
    b = store.create("dev-owner", empty_setup("乙"), slug="yi")
    from playout.runtime import StoryRuntime

    rt = StoryRuntime(store)
    rt.start(a)
    rt.start(store.require(b.id))
    sa = rt.snapshot(store.require(a.id))
    sb = rt.snapshot(store.require(b.id))
    assert sa["title"] == "甲"
    assert sb["title"] == "乙"
    sa["actors"][0]["name"] = "mutated"
    assert sb["actors"][0]["name"] != "mutated"
    rt.close()
    store.close()


def test_non_owner_forbidden(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        story = client.get("/api/stories").json()[0]
        sid = story["id"]
        headers = {"X-User-Id": "stranger", "X-User-Name": "guest"}
        assert client.post(
            f"/api/stories/{sid}/inject", json={"text": "雨"}, headers=headers
        ).status_code == 403
        assert client.post(
            f"/api/stories/{sid}/steer", json={"text": "讓她走"}, headers=headers
        ).status_code == 403
        assert client.post(
            f"/api/stories/{sid}/reset", headers=headers
        ).status_code == 403
        assert client.patch(
            f"/api/stories/{sid}", json={"title": "x"}, headers=headers
        ).status_code == 403
        created = client.post("/api/stories", json={"title": "草稿"}).json()
        assert (
            client.post(
                f"/api/stories/{created['id']}/start", headers=headers
            ).status_code
            == 403
        )
    appmod.close_runtime()


def test_patch_sealed_after_start(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        rec = client.post("/api/stories", json={"title": "封測"}).json()
        sid = rec["id"]
        setup = rec["setup"]
        setup["title"] = "封測"
        setup["worldview"] = "一處靜港。"
        saved = client.patch(f"/api/stories/{sid}", json={"setup": setup})
        assert saved.status_code == 200
        started = client.post(f"/api/stories/{sid}/start")
        assert started.status_code == 200
        assert started.json()["status"] == "live"
        again = client.post(f"/api/stories/{sid}/start")
        assert again.status_code == 409
        sealed = client.patch(
            f"/api/stories/{sid}", json={"setup": {**setup, "worldview": "改了"}}
        )
        assert sealed.status_code == 409
        assert sealed.json()["detail"] == "sealed"
    appmod.close_runtime()


def test_reset_then_patch_and_restart(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        rec = client.post("/api/stories", json={"title": "可改"}).json()
        sid = rec["id"]
        client.post(f"/api/stories/{sid}/start")
        unsealed = client.post(f"/api/stories/{sid}/reset")
        assert unsealed.status_code == 200
        assert unsealed.json()["status"] == "draft"
        setup = unsealed.json()["setup"]
        setup["actors"][0]["name"] = "改名的人"
        patched = client.patch(f"/api/stories/{sid}", json={"setup": setup})
        assert patched.status_code == 200
        client.post(f"/api/stories/{sid}/start")
        snap = client.get(f"/api/stories/{sid}/state").json()
        names = [a["name"] for a in snap["actors"]]
        assert "改名的人" in names
        assert snap["day"] == 1
    appmod.close_runtime()


def test_duplicate_live_is_editable_draft(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        live = next(
            s for s in client.get("/api/stories").json() if s["slug"] == "harbors-end"
        )
        copy = client.post(f"/api/stories/{live['id']}/duplicate").json()
        assert copy["status"] == "draft"
        assert copy["editable"] is True
        assert copy["id"] != live["id"]
        setup = copy["setup"]
        setup["worldview"] = "另一個港。"
        patched = client.patch(f"/api/stories/{copy['id']}", json={"setup": setup})
        assert patched.status_code == 200
        orig = client.get(f"/api/stories/{live['id']}").json()
        assert "另一個港" not in orig["setup"]["worldview"]
        still_live = client.get(f"/api/stories/{live['id']}/state")
        assert still_live.status_code == 200
    appmod.close_runtime()


def test_non_owner_snapshot_redacts_secrets(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        live = next(
            s for s in client.get("/api/stories").json() if s["slug"] == "harbors-end"
        )
        owner = client.get(f"/api/stories/{live['id']}/state").json()
        assert any(a.get("secret") for a in owner["actors"])
        stranger = client.get(
            f"/api/stories/{live['id']}/state",
            headers={"X-User-Id": "stranger"},
        ).json()
        assert all(not a.get("secret") for a in stranger["actors"])
        setup = client.get(
            f"/api/stories/{live['id']}",
            headers={"X-User-Id": "stranger"},
        ).json()["setup"]
        assert all(not a.get("secret") for a in setup["actors"])
    appmod.close_runtime()
