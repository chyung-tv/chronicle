"""Storyteller: natural-language world events become state patches + perceptions."""

from __future__ import annotations

from typing import Any, Iterable

from playout.canon import World
from playout.ids import slugify
from playout.llm import LLM
from playout.models import (
    MAX_ACTORS,
    MAX_LOCATIONS,
    Patch,
    StorytellerPlan,
)
from playout.zh import with_prose

STORYTELLER_SYSTEM = with_prose("""你把人寫的世界事件，變成封閉正史模擬可用的補丁。
不要替人物寫對白。不要派給他們目標。
你只改世界：地方、物件、傷勢、天色、環境逼人移動，以及人能感知到什麼。

只回傳 JSON：
{"summary":"一句已發生之事，繁體中文","patches":[...]}

Patch ops:
{"op":"destroy_location","location_id":"...","detail":"..."}
{"op":"describe_location","location_id":"...","detail":"new description"}
{"op":"add_location","location_id":"...","name":"...","detail":"...","x":0,"y":0,"connect_to":"..."}
{"op":"add_edge","location_id":"...","connect_to":"..."}
{"op":"injure_actor","actor_id":"...","detail":"...","condition":"左臂受傷"}
{"op":"kill_actor","actor_id":"...","detail":"..."}
{"op":"edit_actor","actor_id":"...","detail":"...","condition":"...","mood":"..."}
{"op":"add_actor","actor_id":"...","name":"...","location_id":"...","voice":"...","want":"...","secret":"...","constitution":"...","mood":"...","detail":"..."}
{"op":"move_actor","actor_id":"...","location_id":"...","detail":"environmental reason they are drawn/forced"}
{"op":"add_object","object_id":"...","name":"...","location_id":"...","detail":"description","hidden":false}
{"op":"describe_object","object_id":"...","detail":"new description"}
{"op":"destroy_object","object_id":"...","detail":"..."}
{"op":"reveal_object","object_id":"...","detail":"..."}
{"op":"rumor","actor_ids":["id"],"detail":"what they hear/see now"}
{"op":"broadcast","location_id":"...","detail":"everyone here perceives this"}
{"op":"set_weather","detail":"..."}

規則：
- 只發明從此刻起的新事實。永不改寫過去。
- 毀傷某地時，必須是事件文裡點名的既有地點。不可預設某一處。
- 寧用 rumor/broadcast，少搬人。move_actor 只可到該人當下相鄰且完好的地點，不可瞬移。
detail、summary 一律繁體中文。
""")


def apply_patches(
    world: World,
    plan: StorytellerPlan,
    *,
    kind: str = "world",
    allow: Iterable[str] | None = None,
) -> int:
    allowed = set(allow) if allow is not None else None
    eid = world.append_event(kind, plan.summary)
    for patch in plan.patches:
        if allowed is not None and patch.op not in allowed:
            continue
        _apply_patch(world, eid, patch)
    world.cx.commit()
    return eid


def _add_edge(world: World, a: str, b: str) -> None:
    if not a or not b or a == b:
        return
    try:
        world.location(a)
        world.location(b)
    except Exception:
        return
    world.cx.execute(
        "INSERT INTO edges(a, b) VALUES(?,?) ON CONFLICT(a, b) DO NOTHING",
        (a, b),
    )
    world.cx.execute(
        "INSERT INTO edges(a, b) VALUES(?,?) ON CONFLICT(a, b) DO NOTHING",
        (b, a),
    )


def _apply_patch(world: World, event_id: int, patch: Patch) -> None:
    from playout.models import MoveIntent
    from playout.movement import apply_move

    op = patch.op
    if op == "destroy_location" and patch.location_id:
        try:
            loc = world.location(patch.location_id)
        except Exception:
            return
        world.cx.execute(
            "UPDATE locations SET intact=0, description=? WHERE id=?",
            (patch.detail or f"{loc['name']}已毀。", patch.location_id),
        )
        occupants = world.actors_at(patch.location_id)
        refuge = world.exits(patch.location_id)
        dest = refuge[0].id if refuge else patch.location_id
        for a in occupants:
            world.set_injured(a["id"], True)
            world.perceive(
                event_id,
                a["id"],
                patch.detail or f"{loc['name']}毀了。你受傷，被人趕出來。",
            )
            if dest != patch.location_id:
                apply_move(
                    world,
                    MoveIntent(actor_id=a["id"], to=dest, kind="evacuate"),
                    event_id=event_id,
                )

    elif op == "describe_location" and patch.location_id:
        try:
            world.location(patch.location_id)
        except Exception:
            return
        world.cx.execute(
            "UPDATE locations SET description=? WHERE id=?",
            (patch.detail, patch.location_id),
        )

    elif op == "add_location":
        if world.location_count() >= MAX_LOCATIONS:
            return
        loc_id = patch.location_id or slugify(
            patch.name or "place", "loc", world.used_location_ids()
        )
        existing = None
        try:
            existing = world.location(loc_id)
        except Exception:
            existing = None
        if existing:
            if patch.detail:
                world.cx.execute(
                    "UPDATE locations SET description=? WHERE id=?",
                    (patch.detail, loc_id),
                )
            if patch.name:
                world.cx.execute(
                    "UPDATE locations SET name=? WHERE id=?",
                    (patch.name, loc_id),
                )
        else:
            origin = None
            if patch.connect_to:
                try:
                    origin = world.location(patch.connect_to)
                except Exception:
                    origin = None
            x = patch.x
            y = patch.y
            if x is None:
                x = float(origin["x"] + 80) if origin else 270.0
            if y is None:
                y = float(origin["y"] + 40) if origin else 180.0
            world.cx.execute(
                "INSERT INTO locations(id, name, description, intact, x, y) VALUES(?,?,?,?,?,?)",
                (
                    loc_id,
                    patch.name or loc_id,
                    patch.detail or patch.name or loc_id,
                    1,
                    x,
                    y,
                ),
            )
        if patch.connect_to:
            _add_edge(world, loc_id, patch.connect_to)

    elif op == "add_edge" and patch.location_id and patch.connect_to:
        _add_edge(world, patch.location_id, patch.connect_to)

    elif op == "injure_actor" and patch.actor_id:
        try:
            world.actor(patch.actor_id)
        except Exception:
            return
        world.set_injured(
            patch.actor_id, True, condition=patch.condition or patch.detail
        )
        world.perceive(event_id, patch.actor_id, patch.detail or "你受傷了。")

    elif op == "kill_actor" and patch.actor_id:
        try:
            a = world.actor(patch.actor_id)
        except Exception:
            return
        world.set_alive(patch.actor_id, False)
        world.append_event(
            "world_kill",
            patch.detail or f"{a['name']}死於這場世變。",
            target_id=patch.actor_id,
        )
        for other in world.living_actors():
            if other["location_id"] == a["location_id"]:
                world.perceive(
                    event_id, other["id"], patch.detail or f"{a['name']}死了。"
                )

    elif op == "edit_actor" and patch.actor_id:
        try:
            world.actor(patch.actor_id)
        except Exception:
            return
        if patch.voice:
            world.cx.execute(
                "UPDATE actors SET voice=? WHERE id=?", (patch.voice, patch.actor_id)
            )
        if patch.want:
            world.cx.execute(
                "UPDATE actors SET want=? WHERE id=?", (patch.want, patch.actor_id)
            )
        if patch.secret:
            world.cx.execute(
                "UPDATE actors SET secret=? WHERE id=?", (patch.secret, patch.actor_id)
            )
        if patch.constitution:
            world.cx.execute(
                "UPDATE actors SET constitution=? WHERE id=?",
                (patch.constitution, patch.actor_id),
            )
        if patch.mood:
            world.set_actor_mood(patch.actor_id, patch.mood[:40])
        if patch.condition:
            world.set_injured(patch.actor_id, True, condition=patch.condition)
        elif patch.detail:
            world.set_injured(patch.actor_id, True, condition=patch.detail)
        if patch.detail:
            world.perceive(event_id, patch.actor_id, patch.detail)

    elif op == "add_actor":
        if world.actor_count() >= MAX_ACTORS:
            return
        aid = patch.actor_id or slugify(
            patch.name or "npc", "npc", world.used_actor_ids()
        )
        try:
            world.actor(aid)
            return
        except Exception:
            pass
        loc_id = patch.location_id
        if not loc_id:
            home = world.cx.execute("SELECT id FROM locations LIMIT 1").fetchone()
            loc_id = home["id"] if home else None
        if not loc_id:
            return
        try:
            world.location(loc_id)
        except Exception:
            return
        world.cx.execute(
            """INSERT INTO actors(id, name, voice, want, secret, constitution, location_id, goal, mood, alive, injured, condition)
               VALUES(?,?,?,?,?,?,?,?,?,1,0,?)""",
            (
                aid,
                patch.name or aid,
                patch.voice or "尚未定腔。",
                patch.want or patch.detail or "尚未定願。",
                patch.secret or "",
                patch.constitution or patch.detail or "尚未定性。",
                loc_id,
                patch.goal or patch.want or patch.detail or "尚未定願。",
                patch.mood or "靜",
                patch.condition or "",
            ),
        )
        if patch.detail:
            world.perceive(event_id, aid, patch.detail)

    elif op == "move_actor" and patch.actor_id and patch.location_id:
        apply_move(
            world,
            MoveIntent(
                actor_id=patch.actor_id,
                to=patch.location_id,
                kind="forced",
            ),
            event_id=event_id,
            detail=patch.detail or None,
        )

    elif op == "add_object":
        oid = patch.object_id or slugify(
            patch.name or "object", "obj", world.used_object_ids()
        )
        world.cx.execute(
            """INSERT INTO objects(id, name, description, location_id, holder_id, hidden, destroyed)
               VALUES(?,?,?,?,NULL,?,0)
               ON CONFLICT(id) DO UPDATE SET
                 name=excluded.name,
                 description=excluded.description,
                 location_id=excluded.location_id,
                 holder_id=NULL,
                 hidden=excluded.hidden,
                 destroyed=0""",
            (
                oid,
                patch.name or oid,
                patch.detail or patch.name or oid,
                patch.location_id,
                1 if patch.hidden else 0,
            ),
        )

    elif op == "describe_object" and patch.object_id:
        obj = world.object(patch.object_id)
        if not obj:
            return
        world.cx.execute(
            "UPDATE objects SET description=? WHERE id=?",
            (patch.detail or obj["description"], patch.object_id),
        )
        if patch.name:
            world.cx.execute(
                "UPDATE objects SET name=? WHERE id=?",
                (patch.name, patch.object_id),
            )

    elif op == "destroy_object" and patch.object_id:
        world.cx.execute(
            "UPDATE objects SET destroyed=1 WHERE id=?", (patch.object_id,)
        )

    elif op == "reveal_object" and patch.object_id:
        world.cx.execute("UPDATE objects SET hidden=0 WHERE id=?", (patch.object_id,))
        obj = world.object(patch.object_id)
        if obj and obj["location_id"]:
            for a in world.actors_at(obj["location_id"]):
                world.perceive(
                    event_id, a["id"], patch.detail or f"你看見{obj['name']}。"
                )

    elif op == "rumor":
        ids = patch.actor_ids or ([patch.actor_id] if patch.actor_id else [])
        for aid in ids:
            try:
                world.actor(aid)
            except Exception:
                continue
            world.perceive(event_id, aid, patch.detail)

    elif op == "broadcast":
        if patch.location_id == "*" or not patch.location_id:
            targets = world.living_actors()
        else:
            targets = world.actors_at(patch.location_id)
        for a in targets:
            world.perceive(event_id, a["id"], patch.detail)

    elif op == "set_weather":
        world.set_meta("weather", patch.detail)

    world.cx.commit()


def _heuristic_event(world: World, text: str) -> StorytellerPlan:
    t = text.lower()
    hit = world.find_location(text)
    disaster = (
        "meteor",
        "strike",
        "collapse",
        "fire",
        "explode",
        "wreck",
        "隕石",
        "流星",
        "倒塌",
        "大火",
        "爆炸",
        "墜",
        "毀",
    )
    if any(w in t or w in text for w in disaster):
        if not hit:
            return StorytellerPlan(
                summary=text.strip(),
                patches=[
                    Patch(op="set_weather", detail=text.strip() or "天色驟變。"),
                    Patch(op="broadcast", location_id="*", detail=text.strip()),
                ],
            )
        occupants = world.actors_at(hit["id"])
        patches = [
            Patch(op="destroy_location", location_id=hit["id"], detail=text.strip()),
            Patch(op="set_weather", detail="煙塵與熱風。"),
            Patch(
                op="broadcast",
                location_id="*",
                detail=f"{hit['name']}一震：{text.strip()}",
            ),
        ]
        for a in occupants:
            patches.append(
                Patch(op="injure_actor", actor_id=a["id"], detail="你被掀倒，受傷了。")
            )
        return StorytellerPlan(summary=text.strip(), patches=patches)
    if any(w in t or w in text for w in ("storm", "颱風", "風暴", "暴雨")):
        patches = [
            Patch(op="set_weather", detail=text.strip() or "風雨大作。"),
            Patch(op="broadcast", location_id="*", detail=text.strip()),
        ]
        if hit:
            patches.append(
                Patch(
                    op="describe_location",
                    location_id=hit["id"],
                    detail=f"{hit['name']}裡風雨大作。{text.strip()}",
                )
            )
        return StorytellerPlan(summary=text.strip(), patches=patches)
    if any(w in t or w in text for w in ("letter", "note", "信", "紙條")):
        loc = hit or world.cx.execute(
            "SELECT * FROM locations ORDER BY id LIMIT 1"
        ).fetchone()
        loc_id = loc["id"] if loc else None
        return StorytellerPlan(
            summary=text.strip(),
            patches=[
                Patch(
                    op="add_object",
                    object_id="injected_letter",
                    name="信",
                    location_id=loc_id,
                    detail=text.strip(),
                    hidden=False,
                ),
                Patch(
                    op="broadcast",
                    location_id=loc_id or "*",
                    detail="一封信攤在明處。",
                ),
            ],
        )
    loc_id = hit["id"] if hit else "*"
    return StorytellerPlan(
        summary=text.strip(),
        patches=[Patch(op="broadcast", location_id=loc_id, detail=text.strip())],
    )


def inject_world_event(
    world: World, llm: LLM, text: str, *, kind: str = "world"
) -> dict[str, Any]:
    actors = [
        {"id": a["id"], "name": a["name"], "location": a["location_id"]}
        for a in world.living_actors()
    ]
    locs = [
        {"id": l["id"], "name": l["name"]}
        for l in world.cx.execute("SELECT id, name FROM locations")
    ]
    user = f"事件：{text}\n人物：{actors}\n地點：{locs}\n天色：{world.meta('weather')}"
    plan: StorytellerPlan
    if llm.mode == "live":
        data = llm.complete_json(STORYTELLER_SYSTEM, user, strong=True)
        try:
            plan = StorytellerPlan.model_validate(data)
        except Exception:
            plan = _heuristic_event(world, text)
    else:
        plan = _heuristic_event(world, text)
    if not plan.patches:
        plan = _heuristic_event(world, text)
    eid = apply_patches(world, plan, kind=kind)
    world.set_meta("idle_scenes", "0")
    return {
        "event_id": eid,
        "summary": plan.summary,
        "patches": [p.model_dump() for p in plan.patches],
    }
