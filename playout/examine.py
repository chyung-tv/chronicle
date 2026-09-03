"""Examine resolver: looking writes back to the node. Does not move anyone."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from playout.models import (
    ExamineDiscovery,
    ExamineIntent,
    ExamineResolution,
)
from playout.zh import with_prose

if TYPE_CHECKING:
    from playout.canon import World
    from playout.llm import LLM

LOOK_MARKERS = ("察看", "細看", "搜看", "看看")

EXAMINE_SYSTEM = with_prose("""你是封閉正史模擬的察看解析器，不是人物，也不是小說家。
人物站在一個地點細看某物、搜看此地、或朝相鄰方向望去。你根據此地已有的正史，判定他們真正看見什麼，並把發現寫回世界。

只回傳 JSON，欄位：
- perception: 察看者本人見到的，繁體中文
- summary: 一句已發生之事，寫進事件帶（可含發現；在場旁人的感知另寫）
- object_appends: [{object_id, text}] 把新觀察接到該物件既有描述之後。僅限此地或察看者手上的物件
- location_details: [字串] 接到此地底色之後的新細節。不改寫底色
- add_objects: [{object_id, name, description}] 僅當此地確有一件尚未入冊的可見物。不可把存在別處的物件搬來
- reveal_ids: [object_id] 僅揭開已在此地、原本隱藏的物件

規則：
- 不可讓人物走動。望向相鄰地點不是走到那裡。
- 不可把不在此地的物件生成到此地。負面清單裡的物件仍在原處。痕跡可以暗示方向，但不可把失物放到此地。
- 不可寫其他房間的描述。你只知道此地。
- 望向相鄰方向時：不要 object_appends、不要 add_objects、不要揭開別處隱藏物。最多在此地記一筆遠望的痕跡。
- 不要發明與體質、意圖、眼前之物無關的奇觀。
- perception、summary、細節一律繁體中文。
""")


def is_looking_text(text: str) -> bool:
    raw = text or ""
    return any(m in raw for m in LOOK_MARKERS)


def _name_in_text(name: str, text: str) -> bool:
    if not name or not text:
        return False
    if name in text:
        return True
    if len(name) < 2:
        return False
    for n in range(len(name), 1, -1):
        for i in range(len(name) - n + 1):
            chunk = name[i : i + n]
            if len(chunk) >= 2 and chunk in text:
                return True
    return False


def resolve_examine_aim(world: World, actor_id: str, text: str) -> str:
    actor = world.actor(actor_id)
    here = actor["location_id"]
    raw = text or ""
    low = raw.lower()
    rows: list[Any] = []
    rows.extend(world.visible_objects(here, include_hidden=True))
    rows.extend(world.inventory(actor_id))
    rows.sort(key=lambda o: len(o["name"]), reverse=True)
    for obj in rows:
        if obj["id"] in raw or obj["id"] in low or _name_in_text(obj["name"], raw):
            return obj["id"]
    loc = world.location(here)
    if here in raw or here in low or loc["name"] in raw:
        return here
    for dest_id in world.adjacent(here):
        dest = world.location(dest_id)
        if dest_id in raw or dest_id in low or dest["name"] in raw:
            return dest_id
    for row in world.cx.execute("SELECT id, name FROM locations"):
        if row["id"] in raw or row["id"] in low or row["name"] in raw:
            return row["id"]
    return here


def examine_aims(world: World, actor_id: str) -> list[tuple[str, str]]:
    """(id, label) for the examine tool enum: visible objects, held, here, connected."""
    actor = world.actor(actor_id)
    here = actor["location_id"]
    loc = world.location(here)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(oid: str, label: str) -> None:
        if oid in seen:
            return
        seen.add(oid)
        out.append((oid, label))

    add(here, f"{loc['name']}（此地）")
    for obj in world.visible_objects(here):
        add(obj["id"], f"{obj['name']}（物）")
    for obj in world.inventory(actor_id):
        add(obj["id"], f"{obj['name']}（隨身）")
    for dest_id in world.adjacent(here):
        dest = world.location(dest_id)
        add(dest_id, f"{dest['name']}（望去，不走）")
    return out


def evaluate_examine(world: World, intent: ExamineIntent) -> ExamineResolution:
    try:
        actor = world.actor(intent.actor_id)
    except Exception:
        return ExamineResolution(
            ok=False,
            actor_id=intent.actor_id,
            aim=intent.aim,
            reason="unknown_actor",
            summary="無人可看。",
        )
    here = actor["location_id"]
    if not actor["alive"]:
        return ExamineResolution(
            ok=False,
            actor_id=intent.actor_id,
            aim=intent.aim,
            here_id=here,
            reason="dead",
            summary=f"{actor['name']}已不能看。",
            self_perception="你看不見了。",
        )

    aim = (intent.aim or "").strip()
    obj = world.object(aim) if aim else None
    if obj and not obj["destroyed"]:
        here_obj = (
            obj["location_id"] == here
            or obj["holder_id"] == intent.actor_id
        )
        if not here_obj:
            return ExamineResolution(
                ok=False,
                actor_id=intent.actor_id,
                aim=aim,
                here_id=here,
                reason="not_here",
                summary=f"{actor['name']}夠不著那物。",
                self_perception="那物不在眼前。",
            )
        return ExamineResolution(
            ok=True,
            actor_id=intent.actor_id,
            aim=aim,
            here_id=here,
            kind="object",
        )

    try:
        loc = world.location(aim)
    except Exception:
        loc = None
        if aim:
            for row in world.cx.execute("SELECT * FROM locations"):
                if row["name"] == aim:
                    loc = row
                    aim = row["id"]
                    break
    if loc:
        if loc["id"] == here:
            return ExamineResolution(
                ok=True,
                actor_id=intent.actor_id,
                aim=loc["id"],
                here_id=here,
                kind="place",
            )
        if loc["id"] in world.adjacent(here):
            return ExamineResolution(
                ok=True,
                actor_id=intent.actor_id,
                aim=loc["id"],
                here_id=here,
                kind="look_toward",
            )
        return ExamineResolution(
            ok=False,
            actor_id=intent.actor_id,
            aim=loc["id"],
            here_id=here,
            reason="not_adjacent",
            summary=f"{actor['name']}無法由此望見{loc['name']}。",
            self_perception="那邊望不見。",
        )

    return ExamineResolution(
        ok=False,
        actor_id=intent.actor_id,
        aim=aim,
        here_id=here,
        reason="unknown_target",
        summary=f"{actor['name']}看不清要看什麼。",
        self_perception="你看不清要看什麼。",
    )


def _elsewhere_objects(world: World, here: str, actor_id: str) -> list[dict[str, str]]:
    rows = world.cx.execute(
        """SELECT id, name, location_id, holder_id FROM objects
           WHERE destroyed=0 AND NOT (
             location_id = ? OR holder_id = ?
           )""",
        (here, actor_id),
    )
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "location_id": r["location_id"] or "",
            }
        )
    return out


def examine_brief(world: World, intent: ExamineIntent, res: ExamineResolution) -> str:
    actor = world.actor(intent.actor_id)
    here = res.here_id or actor["location_id"]
    node = world.node(here)
    hidden = [
        {"id": o["id"], "name": o["name"], "description": o["description"]}
        for o in world.visible_objects(here, include_hidden=True)
        if o["hidden"]
    ]
    held = [
        {"id": o["id"], "name": o["name"], "description": o["description"]}
        for o in world.inventory(intent.actor_id)
    ]
    payload = {
        "actor": {
            "id": actor["id"],
            "name": actor["name"],
            "constitution": actor["constitution"],
            "intent": intent.intent,
        },
        "here": {
            "id": node.id,
            "name": node.name,
            "vibe": world.location(here)["description"],
            "details": world.location_detail_texts(here),
            "prose": node.description,
            "people": [p.model_dump() for p in node.present],
            "visible_objects": [o.model_dump() for o in node.visible_objects],
            "hidden_objects_here": hidden,
            "held": held,
        },
        "not_here": _elsewhere_objects(world, here, intent.actor_id),
        "aim": {"id": res.aim, "kind": res.kind},
        "constraint": (
            "不可發現 not_here 清單中的物件。不可寫其他房間的描述。"
            "望去不是走到那裡。"
        ),
    }
    return json.dumps(payload, ensure_ascii=False)


def mock_discover(world: World, intent: ExamineIntent, res: ExamineResolution) -> ExamineDiscovery:
    actor = world.actor(intent.actor_id)
    here = res.here_id
    if res.kind == "object":
        obj = world.object(res.aim)
        assert obj is not None
        reveal: list[str] = []
        if obj["hidden"] and obj["location_id"] == here:
            reveal = [obj["id"]]
        return ExamineDiscovery(
            perception=f"你察看{obj['name']}。{obj['description']}",
            summary=f"{actor['name']}察看{obj['name']}。",
            reveal_ids=reveal,
        )
    if res.kind == "look_toward":
        dest = world.location(res.aim)
        return ExamineDiscovery(
            perception=f"你朝{dest['name']}方向望去。你仍在{world.location(here)['name']}，並未走過去。",
            summary=f"{actor['name']}朝{dest['name']}望去。",
        )
    loc = world.location(here)
    hidden = world.cx.execute(
        "SELECT * FROM objects WHERE location_id=? AND hidden=1 AND destroyed=0",
        (here,),
    ).fetchall()
    reveal_ids = [h["id"] for h in hidden]
    found = ""
    if hidden:
        found = "此處藏有：" + "、".join(h["name"] for h in hidden) + "。"
    return ExamineDiscovery(
        perception=loc["description"] + found,
        summary=f"{actor['name']}搜看{loc['name']}。{found}",
        reveal_ids=reveal_ids,
    )


async def live_discover(
    world: World, intent: ExamineIntent, res: ExamineResolution
) -> ExamineDiscovery:
    from pydantic_ai import Agent

    from playout.agents.model import openrouter_model, strong_model_name

    user = (
        f"場面：{examine_brief(world, intent, res)}\n"
        f"此人試圖：{intent.intent or '細看'}\n"
        f"aim={res.aim} kind={res.kind}"
    )
    agent: Agent[None, ExamineDiscovery] = Agent(
        openrouter_model(strong_model_name()),
        output_type=ExamineDiscovery,
        instructions=EXAMINE_SYSTEM,
    )
    out = await agent.run(user)
    discovery = out.output
    if not isinstance(discovery, ExamineDiscovery):
        return mock_discover(world, intent, res)
    if not (discovery.perception or "").strip():
        fallback = mock_discover(world, intent, res)
        discovery.perception = fallback.perception
    return discovery


def _object_is_here(world: World, object_id: str, here: str, actor_id: str) -> bool:
    obj = world.object(object_id)
    if not obj or obj["destroyed"]:
        return False
    return obj["location_id"] == here or obj["holder_id"] == actor_id


def apply_discovery(
    world: World, intent: ExamineIntent, res: ExamineResolution, discovery: ExamineDiscovery
) -> ExamineResolution:
    actor = world.actor(intent.actor_id)
    here = res.here_id
    looking_away = res.kind == "look_toward"

    reveal_ids: list[str] = []
    if not looking_away:
        for oid in discovery.reveal_ids:
            if _object_is_here(world, oid, here, intent.actor_id):
                obj = world.object(oid)
                if obj and obj["hidden"] and obj["location_id"] == here:
                    world.cx.execute("UPDATE objects SET hidden=0 WHERE id=?", (oid,))
                    reveal_ids.append(oid)
        for app in discovery.object_appends:
            if _object_is_here(world, app.object_id, here, intent.actor_id):
                world.append_object_description(app.object_id, app.text)

    added: list[str] = []
    if not looking_away:
        for found in discovery.add_objects:
            oid = (found.object_id or "").strip()
            if not oid:
                oid = re.sub(r"[^a-z0-9]+", "_", (found.name or "find").lower())[:40]
            if world.object(oid):
                continue
            world.cx.execute(
                """INSERT INTO objects(id, name, description, location_id, holder_id, hidden, destroyed)
                   VALUES(?,?,?,?,NULL,0,0)""",
                (
                    oid,
                    found.name or oid,
                    (found.description or found.name or oid)[:500],
                    here,
                ),
            )
            added.append(oid)

    perception = (discovery.perception or "").strip()[:800]
    summary = (discovery.summary or "").strip()[:800]
    if res.kind == "object":
        obj = world.object(res.aim)
        label = obj["name"] if obj else res.aim
        if not summary:
            summary = f"{actor['name']}察看{label}。"
        if not perception:
            perception = f"你察看{label}。"
        witness = f"{actor['name']}在細看{label}。"
    elif res.kind == "look_toward":
        dest = world.location(res.aim)
        if not summary:
            summary = f"{actor['name']}朝{dest['name']}望去。"
        if not perception:
            perception = f"你朝{dest['name']}方向望去。你並未走過去。"
        witness = f"{actor['name']}朝遠處張望。"
    else:
        loc = world.location(here)
        if not summary:
            summary = f"{actor['name']}搜看{loc['name']}。"
        if not perception:
            perception = loc["description"]
        witness = f"{actor['name']}在細看{loc['name']}。"

    payload: dict[str, Any] = {
        "aim": res.aim,
        "kind": res.kind,
        "intent": intent.intent,
        "location_id": here,
        "reveal_ids": reveal_ids,
        "added_ids": added,
    }
    eid = world.append_event(
        "examine",
        summary,
        actor_id=intent.actor_id,
        payload=payload,
    )

    traces = discovery.location_details[:1] if looking_away else discovery.location_details
    for text in traces:
        if (text or "").strip():
            world.append_location_detail(here, text, eid)

    world.perceive(eid, intent.actor_id, perception)
    for person in world.actors_at(here):
        if person["id"] == intent.actor_id:
            continue
        world.perceive(eid, person["id"], witness)

    world.cx.commit()
    res.ok = True
    res.event_id = eid
    res.summary = summary
    res.self_perception = perception
    res.witness_perception = witness
    return res


def _seal_failed(world: World, res: ExamineResolution) -> ExamineResolution:
    eid = world.append_event(
        "failed_examine",
        res.summary or "看不成。",
        actor_id=res.actor_id,
        payload={"aim": res.aim, "reason": res.reason, "location_id": res.here_id},
    )
    if res.self_perception:
        world.perceive(eid, res.actor_id, res.self_perception)
    res.event_id = eid
    return res


def apply_examine(
    world: World,
    intent: ExamineIntent,
    *,
    discovery: ExamineDiscovery | None = None,
    llm: LLM | None = None,
) -> ExamineResolution:
    """Sync path. Live LLM discovery must go through apply_examine_async."""
    res = evaluate_examine(world, intent)
    if not res.ok:
        return _seal_failed(world, res)
    if discovery is None:
        discovery = mock_discover(world, intent, res)
        if llm is not None and getattr(llm, "mode", "mock") == "live":
            # Sync callers cannot await; mock is the deterministic apply.
            discovery = mock_discover(world, intent, res)
    return apply_discovery(world, intent, res, discovery)


async def apply_examine_async(
    world: World,
    intent: ExamineIntent,
    llm: LLM | None = None,
    *,
    discovery: ExamineDiscovery | None = None,
) -> ExamineResolution:
    from playout.agents.model import llm_mode

    res = evaluate_examine(world, intent)
    if not res.ok:
        return _seal_failed(world, res)
    if discovery is None:
        live = bool(llm) and getattr(llm, "mode", "mock") == "live" and llm_mode() == "live"
        if live:
            try:
                discovery = await live_discover(world, intent, res)
            except Exception:
                discovery = mock_discover(world, intent, res)
        else:
            discovery = mock_discover(world, intent, res)
    return apply_discovery(world, intent, res, discovery)


def resolution_as_result(res: ExamineResolution) -> dict[str, Any]:
    return {
        "ok": res.ok,
        "event_id": res.event_id,
        "reason": res.reason,
        "summary": res.summary,
        "kind": "examine" if res.ok else "failed_examine",
    }
