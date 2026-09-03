"""Storyteller: natural-language world events become state patches + perceptions."""

from __future__ import annotations

import re
from typing import Any

from playout.canon import World
from playout.llm import LLM
from playout.models import Patch, StorytellerPlan
from playout.zh import with_prose

STORYTELLER_SYSTEM = with_prose("""你把人寫的世界事件，變成封閉正史模擬可用的補丁。
不要替人物寫對白。不要派給他們目標。
你只改世界：地方、物件、傷勢、天色、環境逼人移動，以及人能感知到什麼。

只回傳 JSON：
{"summary":"一句已發生之事，繁體中文","patches":[...]}

Patch ops:
{"op":"destroy_location","location_id":"...","detail":"..."}
{"op":"describe_location","location_id":"...","detail":"new description"}
{"op":"injure_actor","actor_id":"...","detail":"..."}
{"op":"kill_actor","actor_id":"...","detail":"..."}  // only if the event itself kills (meteor, collapse)
{"op":"move_actor","actor_id":"...","location_id":"...","detail":"environmental reason they are drawn/forced"}
{"op":"add_object","object_id":"...","name":"...","location_id":"...","detail":"description","hidden":false}
{"op":"destroy_object","object_id":"...","detail":"..."}
{"op":"reveal_object","object_id":"...","detail":"..."}
{"op":"rumor","actor_ids":["id"],"detail":"what they hear/see now"}
{"op":"broadcast","location_id":"...","detail":"everyone here perceives this"}  // location_id "*" for all living
{"op":"set_weather","detail":"..."}

規則：
- 只發明從此刻起的新事實。永不改寫過去。
- 若隕石擊中某地，毀傷該地，並傷及在場之人。
- 寧用 rumor/broadcast，少搬人。move_actor 只可到該人當下相鄰且完好的地點，不可瞬移。
detail、summary 一律繁體中文。
""")


def apply_patches(world: World, plan: StorytellerPlan, *, kind: str = "world") -> int:
    eid = world.append_event(kind, plan.summary)
    for patch in plan.patches:
        _apply_patch(world, eid, patch)
    world.cx.commit()
    return eid


def _apply_patch(world: World, event_id: int, patch: Patch) -> None:
    from playout.models import MoveIntent
    from playout.movement import apply_move

    op = patch.op
    if op == "destroy_location" and patch.location_id:
        loc = world.location(patch.location_id)
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
        world.cx.execute(
            "UPDATE locations SET description=? WHERE id=?",
            (patch.detail, patch.location_id),
        )

    elif op == "injure_actor" and patch.actor_id:
        world.set_injured(patch.actor_id, True)
        world.perceive(event_id, patch.actor_id, patch.detail or "你受傷了。")

    elif op == "kill_actor" and patch.actor_id:
        a = world.actor(patch.actor_id)
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
        oid = patch.object_id or re.sub(
            r"[^a-z0-9]+", "_", (patch.name or "object").lower()
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
    locs = list(world.cx.execute("SELECT * FROM locations"))
    hit = None
    for loc in locs:
        if loc["id"] in t or loc["name"].lower() in t or loc["name"] in text:
            hit = loc
            break
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
    )
    if any(w in t or w in text for w in disaster):
        loc = hit or world.location("quay")
        occupants = world.actors_at(loc["id"])
        patches = [
            Patch(op="destroy_location", location_id=loc["id"], detail=text.strip()),
            Patch(op="set_weather", detail="煙氣與燙風自水面來"),
            Patch(
                op="broadcast",
                location_id="*",
                detail=f"{loc['name']}一震：{text.strip()}",
            ),
        ]
        for a in occupants:
            patches.append(
                Patch(op="injure_actor", actor_id=a["id"], detail="你被掀倒，受傷了。")
            )
        return StorytellerPlan(summary=text.strip(), patches=patches)
    if any(w in t or w in text for w in ("storm", "颱風", "風暴", "暴雨")):
        return StorytellerPlan(
            summary=text.strip(),
            patches=[
                Patch(op="set_weather", detail="風提早到了：雨如礫，海水漫過碼頭"),
                Patch(op="broadcast", location_id="*", detail=text.strip()),
                Patch(
                    op="describe_location",
                    location_id="quay",
                    detail="浪砸碼頭。空繩在風裡抽。",
                ),
            ],
        )
    if any(w in t or w in text for w in ("letter", "note", "信", "紙條")):
        loc_id = hit["id"] if hit else "bakery"
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
                Patch(op="broadcast", location_id=loc_id, detail="一封信攤在明處。"),
            ],
        )
    # generic: everyone at a mentioned place, else all, perceives it
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
