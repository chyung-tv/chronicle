"""Referee: structured actions become canon. LLMs propose; this applies or rejects."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from playout.models import (
    Action,
    AttackAction,
    DropAction,
    ExamineAction,
    KillAction,
    MoveAction,
    SpeakAction,
    TakeAction,
    WaitAction,
    WriteNoteAction,
)

if TYPE_CHECKING:
    from playout.canon import World


def _witnesses(world: World, loc_id: str, exclude: set[str]) -> list[str]:
    return [a["id"] for a in world.actors_at(loc_id) if a["id"] not in exclude]


def _has_weapon(world: World, actor_id: str) -> bool:
    for obj in world.inventory(actor_id):
        blob = (obj["name"] + " " + obj["description"]).lower()
        if any(w in blob for w in ("knife", "knife", "cleaver", "hook", "club", "pistol", "blade", "gaff")):
            return True
    return False


def apply_action(world: World, actor_id: str, action: Action) -> dict:
    actor = world.actor(actor_id)
    if not actor["alive"]:
        return {"ok": False, "reason": "dead"}

    if isinstance(action, WaitAction):
        eid = world.append_event("wait", f"{actor['name']} waits.", actor_id=actor_id)
        world.perceive(eid, actor_id, "You wait, listening.")
        return {"ok": True, "event_id": eid}

    if isinstance(action, MoveAction):
        if action.to not in world.adjacent(actor["location_id"]):
            eid = world.append_event(
                "failed_move",
                f"{actor['name']} cannot reach {action.to} from here.",
                actor_id=actor_id,
                payload={"to": action.to},
            )
            world.perceive(eid, actor_id, "That place is not adjacent.")
            return {"ok": False, "event_id": eid, "reason": "not_adjacent"}
        dest = world.location(action.to)
        if not dest["intact"]:
            eid = world.append_event(
                "failed_move",
                f"{actor['name']} finds {dest['name']} ruined and impassable.",
                actor_id=actor_id,
            )
            world.perceive(eid, actor_id, f"{dest['name']} is ruined.")
            return {"ok": False, "event_id": eid, "reason": "ruined"}
        here = actor["location_id"]
        world.set_actor_location(actor_id, action.to)
        eid = world.append_event(
            "move",
            f"{actor['name']} goes to {dest['name']}.",
            actor_id=actor_id,
            payload={"from": here, "to": action.to},
        )
        for wid in _witnesses(world, here, {actor_id}):
            world.perceive(eid, wid, f"{actor['name']} leaves toward {dest['name']}.")
        world.perceive(eid, actor_id, f"You arrive at {dest['name']}. {dest['description']}")
        for wid in _witnesses(world, action.to, {actor_id}):
            world.perceive(eid, wid, f"{actor['name']} arrives.")
        return {"ok": True, "event_id": eid}

    if isinstance(action, SpeakAction):
        try:
            target = world.actor(action.target)
        except Exception:
            return {"ok": False, "reason": "unknown_target"}
        if target["location_id"] != actor["location_id"] or not target["alive"]:
            eid = world.append_event(
                "failed_speak",
                f"{actor['name']} tries to speak to {action.target}, who is not here.",
                actor_id=actor_id,
                target_id=action.target,
            )
            world.perceive(eid, actor_id, "They are not here.")
            return {"ok": False, "event_id": eid, "reason": "not_here"}
        speech = action.speech.strip()[:800]
        eid = world.append_event(
            "speak",
            f"{actor['name']} to {target['name']}: \"{speech}\"",
            actor_id=actor_id,
            target_id=action.target,
            payload={"speech": speech},
        )
        world.perceive(eid, actor_id, f"You say to {target['name']}: \"{speech}\"")
        world.perceive(eid, action.target, f"{actor['name']} says to you: \"{speech}\"")
        for wid in _witnesses(world, actor["location_id"], {actor_id, action.target}):
            world.perceive(eid, wid, f"{actor['name']} says to {target['name']}: \"{speech}\"")
        return {"ok": True, "event_id": eid, "expect_reaction": action.target}

    if isinstance(action, TakeAction):
        obj = world.object(action.object_id)
        if not obj or obj["destroyed"] or obj["hidden"]:
            return {"ok": False, "reason": "no_object"}
        if obj["location_id"] != actor["location_id"] or obj["holder_id"]:
            return {"ok": False, "reason": "not_here"}
        world.cx.execute(
            "UPDATE objects SET holder_id=?, location_id=NULL WHERE id=?",
            (actor_id, action.object_id),
        )
        world.cx.commit()
        eid = world.append_event(
            "take",
            f"{actor['name']} takes the {obj['name']}.",
            actor_id=actor_id,
            payload={"object_id": action.object_id},
        )
        world.perceive(eid, actor_id, f"You take the {obj['name']}.")
        for wid in _witnesses(world, actor["location_id"], {actor_id}):
            world.perceive(eid, wid, f"{actor['name']} takes the {obj['name']}.")
        return {"ok": True, "event_id": eid}

    if isinstance(action, DropAction):
        obj = world.object(action.object_id)
        if not obj or obj["holder_id"] != actor_id:
            return {"ok": False, "reason": "not_held"}
        world.cx.execute(
            "UPDATE objects SET holder_id=NULL, location_id=? WHERE id=?",
            (actor["location_id"], action.object_id),
        )
        world.cx.commit()
        eid = world.append_event(
            "drop",
            f"{actor['name']} drops the {obj['name']}.",
            actor_id=actor_id,
            payload={"object_id": action.object_id},
        )
        world.perceive(eid, actor_id, f"You drop the {obj['name']}.")
        for wid in _witnesses(world, actor["location_id"], {actor_id}):
            world.perceive(eid, wid, f"{actor['name']} drops the {obj['name']}.")
        return {"ok": True, "event_id": eid}

    if isinstance(action, ExamineAction):
        obj = world.object(action.target)
        if obj and not obj["destroyed"]:
            here = obj["location_id"] == actor["location_id"] or obj["holder_id"] == actor_id
            if obj["hidden"] and obj["location_id"] == actor["location_id"]:
                world.cx.execute("UPDATE objects SET hidden=0 WHERE id=?", (obj["id"],))
                world.cx.commit()
                here = True
            if not here:
                return {"ok": False, "reason": "not_here"}
            eid = world.append_event(
                "examine",
                f"{actor['name']} examines the {obj['name']}: {obj['description']}",
                actor_id=actor_id,
                payload={"object_id": obj["id"]},
            )
            world.perceive(eid, actor_id, f"You examine the {obj['name']}. {obj['description']}")
            for wid in _witnesses(world, actor["location_id"], {actor_id}):
                world.perceive(eid, wid, f"{actor['name']} looks closely at the {obj['name']}.")
            return {"ok": True, "event_id": eid}
        if action.target == actor["location_id"] or action.target in (
            world.location(actor["location_id"])["name"].lower(),
        ):
            loc = world.location(actor["location_id"])
            hidden = world.cx.execute(
                "SELECT * FROM objects WHERE location_id=? AND hidden=1 AND destroyed=0",
                (loc["id"],),
            ).fetchall()
            found = ""
            if hidden:
                for h in hidden:
                    world.cx.execute("UPDATE objects SET hidden=0 WHERE id=?", (h["id"],))
                world.cx.commit()
                found = " Hidden here: " + ", ".join(h["name"] for h in hidden) + "."
            eid = world.append_event(
                "examine",
                f"{actor['name']} searches {loc['name']}.{found}",
                actor_id=actor_id,
            )
            world.perceive(eid, actor_id, loc["description"] + found)
            return {"ok": True, "event_id": eid}
        return {"ok": False, "reason": "unknown_target"}

    if isinstance(action, WriteNoteAction):
        slug = re.sub(r"[^a-z0-9]+", "_", action.text.lower())[:24]
        oid = f"note_{actor_id}_{world.day}_{world.scene}_{slug}"[:60]
        world.cx.execute(
            """INSERT OR REPLACE INTO objects(id, name, description, location_id, holder_id, hidden, destroyed)
               VALUES(?,?,?,?,?,0,0)""",
            (oid, "note", action.text[:500], None, actor_id),
        )
        world.cx.commit()
        eid = world.append_event(
            "write_note",
            f"{actor['name']} writes a note: \"{action.text[:200]}\"",
            actor_id=actor_id,
            payload={"object_id": oid},
        )
        world.perceive(eid, actor_id, f"You write: {action.text[:200]}")
        return {"ok": True, "event_id": eid}

    if isinstance(action, AttackAction):
        return _violence(world, actor, action.target, lethal=False)

    if isinstance(action, KillAction):
        return _violence(world, actor, action.target, lethal=True)

    return {"ok": False, "reason": "unknown_action"}


def _violence(world: World, actor, target_id: str, lethal: bool) -> dict:
    try:
        target = world.actor(target_id)
    except Exception:
        return {"ok": False, "reason": "unknown_target"}
    if not target["alive"] or target["location_id"] != actor["location_id"]:
        eid = world.append_event(
            "failed_attack",
            f"{actor['name']} cannot reach {target_id}.",
            actor_id=actor["id"],
            target_id=target_id,
        )
        world.perceive(eid, actor["id"], "They are not here.")
        return {"ok": False, "event_id": eid, "reason": "not_here"}

    weapon = _has_weapon(world, actor["id"])
    loc = actor["location_id"]
    if lethal:
        success = weapon or bool(target["injured"])
        if success:
            world.set_alive(target_id, False)
            eid = world.append_event(
                "kill",
                f"{actor['name']} kills {target['name']}.",
                actor_id=actor["id"],
                target_id=target_id,
                payload={"weapon": weapon},
            )
            world.perceive(eid, actor["id"], f"You kill {target['name']}.")
            for wid in _witnesses(world, loc, {actor["id"], target_id}):
                world.perceive(eid, wid, f"You witness {actor['name']} kill {target['name']}.")
            world.bump_relationship(actor["id"], target_id, resentment=3, note="killed them")
            return {"ok": True, "event_id": eid, "killed": True}
        world.set_injured(target_id, True)
        eid = world.append_event(
            "attempted_kill",
            f"{actor['name']} tries to kill {target['name']} and fails; {target['name']} is injured.",
            actor_id=actor["id"],
            target_id=target_id,
        )
        world.perceive(eid, actor["id"], f"You fail to kill {target['name']}. They are hurt and they know.")
        world.perceive(eid, target_id, f"{actor['name']} tries to kill you. You are injured.")
        for wid in _witnesses(world, loc, {actor["id"], target_id}):
            world.perceive(eid, wid, f"{actor['name']} attacks {target['name']} with murderous intent.")
        world.bump_relationship(target_id, actor["id"], trust=-5, resentment=5, note="tried to kill me")
        return {"ok": True, "event_id": eid, "killed": False, "expect_reaction": target_id}

    world.set_injured(target_id, True)
    eid = world.append_event(
        "attack",
        f"{actor['name']} attacks {target['name']}. {target['name']} is injured.",
        actor_id=actor["id"],
        target_id=target_id,
    )
    world.perceive(eid, actor["id"], f"You attack {target['name']}.")
    world.perceive(eid, target_id, f"{actor['name']} attacks you. You are injured.")
    for wid in _witnesses(world, loc, {actor["id"], target_id}):
        world.perceive(eid, wid, f"{actor['name']} attacks {target['name']}.")
    world.bump_relationship(target_id, actor["id"], trust=-3, resentment=3, note="attacked me")
    return {"ok": True, "event_id": eid, "expect_reaction": target_id}
