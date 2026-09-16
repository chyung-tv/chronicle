"""Privacy matrix: audience vs owner, catalog visibility, who may tick."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import GUEST_HEADERS, OWNER_HEADERS
from playout.privacy import redact_snapshot
import playout.app as appmod


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYOUT_CATALOG", str(tmp_path / "catalog.db"))
    monkeypatch.setenv("PLAYOUT_STORIES_DIR", str(tmp_path / "stories"))
    monkeypatch.setenv("PLAYOUT_DEV_USER_ID", "dev-owner")
    appmod.close_runtime()


def _client(tmp_path, monkeypatch) -> TestClient:
    _env(tmp_path, monkeypatch)
    return TestClient(appmod.app)


def _harbors(client: TestClient) -> dict:
    stories = client.get("/api/stories", headers=OWNER_HEADERS).json()
    return next(s for s in stories if s["slug"] == "harbors-end")


def test_redact_snapshot_keeps_inspect_fields_strips_owner_only():
    snap = {
        "actors": [
            {
                "id": "a1",
                "secret": "藏起的信",
                "goal": "找回舢板",
                "mood": "不安",
                "want": "安穩",
            }
        ],
        "diaries": {"a1": [{"day": 1, "text": "碼頭有人盯住我。"}]},
        "intents": [
            {
                "text": "讓她沉船",
                "campaign": {"rungs": [{"id": "motive", "status": "brewing"}]},
            }
        ],
        "day_plan": {
            "slots": [{"kind": "event", "source": "steer", "rung_id": "motive"}]
        },
        "events": [
            {"id": 1, "kind": "speak", "summary": "你聽過風聲沒。"},
            {"id": 2, "kind": "steer_motive", "summary": "導引·動機"},
            {"id": 3, "kind": "steer_means", "summary": "導引·手段"},
        ],
        "chapters": [{"id": 1, "text": "那晚潮水不退。"}],
    }
    out = redact_snapshot(snap)
    act = out["actors"][0]
    assert act["secret"] == ""
    assert act["goal"] == "找回舢板"
    assert act["mood"] == "不安"
    assert act["want"] == "安穩"
    assert out["diaries"]["a1"][0]["text"] == "碼頭有人盯住我。"
    assert out["intents"] == []
    assert out["day_plan"] is None
    kinds = [e["kind"] for e in out["events"]]
    assert kinds == ["speak"]
    assert out["chapters"][0]["text"] == "那晚潮水不退。"
    assert snap["actors"][0]["secret"] == "藏起的信"
    assert snap["intents"]


def test_unsigned_me_is_audience_not_owner(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        me = client.get("/api/me").json()
        assert me["id"] == "audience"
        stories = client.get("/api/stories").json()
        assert len(stories) == 1
        s = stories[0]
        assert s["slug"] == "harbors-end"
        assert s["visibility"] == "public"
        assert s["status"] == "live"
        assert s["is_owner"] is False
        assert s["can_tick"] is False
        assert s["can_god"] is False
        owned = client.get("/api/stories", headers=OWNER_HEADERS).json()
        h = next(x for x in owned if x["slug"] == "harbors-end")
        assert h["is_owner"] is True
        assert h["can_tick"] is True
    appmod.close_runtime()


def test_catalog_hides_others_drafts(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        draft = client.post(
            "/api/stories", json={"title": "私稿"}, headers=OWNER_HEADERS
        ).json()
        assert draft["status"] == "draft"
        assert draft["visibility"] == "private"
        guest_list = client.get("/api/stories", headers=GUEST_HEADERS).json()
        slugs = {s["slug"] for s in guest_list}
        assert "harbors-end" in slugs
        assert draft["id"] not in {s["id"] for s in guest_list}
        hidden = client.get(
            f"/api/stories/{draft['id']}", headers=GUEST_HEADERS
        )
        assert hidden.status_code == 404
        owner_list = client.get("/api/stories", headers=OWNER_HEADERS).json()
        assert draft["id"] in {s["id"] for s in owner_list}
    appmod.close_runtime()


def test_guest_cannot_tick_or_day_or_reset(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        sid = _harbors(client)["id"]
        assert (
            client.post(f"/api/stories/{sid}/tick", headers=GUEST_HEADERS).status_code
            == 403
        )
        assert (
            client.post(f"/api/stories/{sid}/day", headers=GUEST_HEADERS).status_code
            == 403
        )
        assert (
            client.post(f"/api/stories/{sid}/reset", headers=GUEST_HEADERS).status_code
            == 403
        )
        unsigned = client.post(f"/api/stories/{sid}/tick")
        assert unsigned.status_code == 403
        ok = client.post(f"/api/stories/{sid}/tick", headers=OWNER_HEADERS)
        assert ok.status_code == 200
        assert ok.json().get("accepted") is True
    appmod.close_runtime()


def test_audience_snapshot_privacy_matrix(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        sid = _harbors(client)["id"]
        owner = client.get(
            f"/api/stories/{sid}/state", headers=OWNER_HEADERS
        ).json()
        guest = client.get(
            f"/api/stories/{sid}/state", headers=GUEST_HEADERS
        ).json()
        assert any(a.get("secret") for a in owner["actors"])
        assert all(not a.get("secret") for a in guest["actors"])
        assert guest["intents"] == []
        assert guest["day_plan"] is None
        assert guest["can_tick"] is False
        assert guest["can_god"] is False
        assert guest["is_owner"] is False
        assert owner["can_tick"] is True
        assert owner.get("intents") is not None
        guest_kinds = {e["kind"] for e in guest["events"]}
        assert not guest_kinds.intersection(
            {"steer_motive", "steer_means", "steer_opportunity", "steer_escalation"}
        )
        for a in guest["actors"]:
            assert "goal" in a
            assert "mood" in a
        assert isinstance(guest["diaries"], dict)
        assert "chapters" in guest
        setup = client.get(f"/api/stories/{sid}", headers=GUEST_HEADERS).json()[
            "setup"
        ]
        assert all(not a.get("secret") for a in setup["actors"])
        assert any(a.get("goal") for a in setup["actors"])
    appmod.close_runtime()


def test_harbors_end_is_public_live_demo(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        s = _harbors(client)
        assert s["slug"] == "harbors-end"
        assert s["title"] == "港尾"
        assert s["visibility"] == "public"
        assert s["status"] == "live"
        guest = client.get(
            f"/api/stories/{s['id']}", headers=GUEST_HEADERS
        ).json()
        assert guest["visibility"] == "public"
        assert guest["is_owner"] is False
        copy = client.post(
            f"/api/stories/{s['id']}/duplicate", headers=GUEST_HEADERS
        ).json()
        assert copy["status"] == "draft"
        assert copy["visibility"] == "private"
        assert copy["is_owner"] is True
    appmod.close_runtime()
