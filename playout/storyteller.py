"""Storyteller: natural-language world events become state patches + perceptions."""

from __future__ import annotations

import re
from typing import Any

from playout.canon import World
from playout.llm import LLM
from playout.models import Patch, StorytellerPlan

STORYTELLER_SYSTEM = """You convert a human world event into structured patches for a sealed-canon story sim.
You do NOT write dialogue for characters. You do NOT assign them goals.
You only change the world: places, objects, injuries, weather, who is forced to move by the environment, and what people can perceive.

Return JSON:
{"summary":"one sentence that happened","patches":[...]}

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

Rules:
- Invent only NEW facts from now on. Never rewrite the past.
- If a meteor hits a place, destroy or damage that location and injure people who are there.
- Prefer rumor/broadcast over moving actors. Move only as stage direction (crowd, fire, shout).
"""


def apply_patches(world: World, plan: StorytellerPlan, *, kind: str = "world") -> int:
    eid = world.append_event(kind, plan.summary)
    for patch in plan.patches:
        _apply_patch(world, eid, patch)
    world.cx.commit()
    return eid


def _apply_patch(world: World, event_id: int, patch: Patch) -> None:
    op = patch.op
    if op == "destroy_location" and patch.location_id:
        loc = world.location(patch.location_id)
        world.cx.execute(
            "UPDATE locations SET intact=0, description=? WHERE id=?",
            (patch.detail or f"{loc['name']} is ruined.", patch.location_id),
        )
        occupants = world.actors_at(patch.location_id)
        adj = world.adjacent(patch.location_id)
        refuge = adj[0] if adj else patch.location_id
        for a in occupants:
            world.set_injured(a["id"], True)
            if refuge != patch.location_id:
                world.set_actor_location(a["id"], refuge)
            world.perceive(
                event_id,
                a["id"],
                patch.detail or f"{loc['name']} is destroyed. You are hurt and driven out.",
            )

    elif op == "describe_location" and patch.location_id:
        world.cx.execute(
            "UPDATE locations SET description=? WHERE id=?",
            (patch.detail, patch.location_id),
        )

    elif op == "injure_actor" and patch.actor_id:
        world.set_injured(patch.actor_id, True)
        world.perceive(event_id, patch.actor_id, patch.detail or "You are injured.")

    elif op == "kill_actor" and patch.actor_id:
        a = world.actor(patch.actor_id)
        world.set_alive(patch.actor_id, False)
        world.append_event(
            "world_kill",
            patch.detail or f"{a['name']} is killed by the world event.",
            target_id=patch.actor_id,
        )
        for other in world.living_actors():
            if other["location_id"] == a["location_id"]:
                world.perceive(event_id, other["id"], patch.detail or f"{a['name']} is dead.")

    elif op == "move_actor" and patch.actor_id and patch.location_id:
        a = world.actor(patch.actor_id)
        if a["alive"]:
            world.set_actor_location(patch.actor_id, patch.location_id)
            dest = world.location(patch.location_id)
            world.perceive(
                event_id,
                patch.actor_id,
                patch.detail or f"You are drawn to {dest['name']}.",
            )

    elif op == "add_object":
        oid = patch.object_id or re.sub(r"[^a-z0-9]+", "_", (patch.name or "object").lower())
        world.cx.execute(
            """INSERT OR REPLACE INTO objects(id, name, description, location_id, holder_id, hidden, destroyed)
               VALUES(?,?,?,?,NULL,?,0)""",
            (
                oid,
                patch.name or oid,
                patch.detail or patch.name or oid,
                patch.location_id,
                1 if patch.hidden else 0,
            ),
        )

    elif op == "destroy_object" and patch.object_id:
        world.cx.execute("UPDATE objects SET destroyed=1 WHERE id=?", (patch.object_id,))

    elif op == "reveal_object" and patch.object_id:
        world.cx.execute("UPDATE objects SET hidden=0 WHERE id=?", (patch.object_id,))
        obj = world.object(patch.object_id)
        if obj and obj["location_id"]:
            for a in world.actors_at(obj["location_id"]):
                world.perceive(event_id, a["id"], patch.detail or f"You notice the {obj['name']}.")

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
        if loc["id"] in t or loc["name"].lower() in t:
            hit = loc
            break
    if any(w in t for w in ("meteor", "strike", "collapse", "fire", "explode", "wreck")):
        loc = hit or world.location("quay")
        occupants = world.actors_at(loc["id"])
        patches = [
            Patch(op="destroy_location", location_id=loc["id"], detail=text.strip()),
            Patch(op="set_weather", detail="smoke and a hot wind off the water"),
            Patch(op="broadcast", location_id="*", detail=f"A shock from {loc['name']}: {text.strip()}"),
        ]
        for a in occupants:
            patches.append(Patch(op="injure_actor", actor_id=a["id"], detail="You are thrown down, hurt."))
        return StorytellerPlan(summary=text.strip(), patches=patches)
    if "storm" in t:
        return StorytellerPlan(
            summary=text.strip(),
            patches=[
                Patch(op="set_weather", detail="the storm arrives early: rain like gravel, sea over the quay"),
                Patch(op="broadcast", location_id="*", detail=text.strip()),
                Patch(op="describe_location", location_id="quay", detail="Waves smash the quay. Ropes lash empty air."),
            ],
        )
    if "letter" in t or "note" in t:
        loc_id = hit["id"] if hit else "bakery"
        return StorytellerPlan(
            summary=text.strip(),
            patches=[
                Patch(
                    op="add_object",
                    object_id="injected_letter",
                    name="letter",
                    location_id=loc_id,
                    detail=text.strip(),
                    hidden=False,
                ),
                Patch(op="broadcast", location_id=loc_id, detail="A letter is lying in the open."),
            ],
        )
    # generic: everyone at a mentioned place, else all, perceives it
    loc_id = hit["id"] if hit else "*"
    return StorytellerPlan(
        summary=text.strip(),
        patches=[Patch(op="broadcast", location_id=loc_id, detail=text.strip())],
    )


def inject_world_event(world: World, llm: LLM, text: str, *, kind: str = "world") -> dict[str, Any]:
    actors = [{"id": a["id"], "name": a["name"], "location": a["location_id"]} for a in world.living_actors()]
    locs = [{"id": l["id"], "name": l["name"]} for l in world.cx.execute("SELECT id, name FROM locations")]
    user = f"Event: {text}\nActors: {actors}\nLocations: {locs}\nCurrent weather: {world.meta('weather')}"
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
    return {"event_id": eid, "summary": plan.summary, "patches": [p.model_dump() for p in plan.patches]}
