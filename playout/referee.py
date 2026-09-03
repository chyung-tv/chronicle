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

_WEAPON = (
    "knife",
    "cleaver",
    "hook",
    "club",
    "pistol",
    "blade",
    "gaff",
    "刀",
    "菜刀",
    "魚刀",
    "斧",
    "槍",
    "鉤",
)


def _witnesses(world: World, loc_id: str, exclude: set[str]) -> list[str]:
    return [a["id"] for a in world.actors_at(loc_id) if a["id"] not in exclude]


def _has_weapon(world: World, actor_id: str) -> bool:
    for obj in world.inventory(actor_id):
        blob = obj["name"] + " " + obj["description"]
        low = blob.lower()
        if any(w in low or w in blob for w in _WEAPON):
            return True
    return False


def apply_action(world: World, actor_id: str, action: Action) -> dict:
    actor = world.actor(actor_id)
    if not actor["alive"]:
        return {"ok": False, "reason": "dead"}

    if isinstance(action, WaitAction):
        eid = world.append_event("wait", f"{actor['name']}等候。", actor_id=actor_id)
        world.perceive(eid, actor_id, "你等候，聽著。")
        return {"ok": True, "event_id": eid}

    if isinstance(action, MoveAction):
        from playout.models import MoveIntent
        from playout.movement import apply_move

        res = apply_move(world, MoveIntent(actor_id=actor_id, to=action.to))
        return {
            "ok": res.ok,
            "event_id": res.event_id,
            "reason": res.reason,
        }

    if isinstance(action, SpeakAction):
        try:
            target = world.actor(action.target)
        except Exception:
            return {"ok": False, "reason": "unknown_target"}
        if target["location_id"] != actor["location_id"] or not target["alive"]:
            eid = world.append_event(
                "failed_speak",
                f"{actor['name']}想對{action.target}說話，對方不在此。",
                actor_id=actor_id,
                target_id=action.target,
            )
            world.perceive(eid, actor_id, "他們不在這裡。")
            return {"ok": False, "event_id": eid, "reason": "not_here"}
        speech = action.speech.strip()[:800]
        eid = world.append_event(
            "speak",
            f"{actor['name']}對{target['name']}道：「{speech}」",
            actor_id=actor_id,
            target_id=action.target,
            payload={
                "speech": speech,
                "speeches": [
                    {
                        "speaker_id": actor_id,
                        "hearer_id": action.target,
                        "text": speech,
                    }
                ],
                "location_id": actor["location_id"],
            },
        )
        world.perceive(eid, actor_id, f"你對{target['name']}道：「{speech}」")
        world.perceive(eid, action.target, f"{actor['name']}對你道：「{speech}」")
        for wid in _witnesses(world, actor["location_id"], {actor_id, action.target}):
            world.perceive(
                eid, wid, f"{actor['name']}對{target['name']}道：「{speech}」"
            )
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
            f"{actor['name']}取走{obj['name']}。",
            actor_id=actor_id,
            payload={"object_id": action.object_id},
        )
        world.perceive(eid, actor_id, f"你取走{obj['name']}。")
        for wid in _witnesses(world, actor["location_id"], {actor_id}):
            world.perceive(eid, wid, f"{actor['name']}取走{obj['name']}。")
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
            f"{actor['name']}放下{obj['name']}。",
            actor_id=actor_id,
            payload={"object_id": action.object_id},
        )
        world.perceive(eid, actor_id, f"你放下{obj['name']}。")
        for wid in _witnesses(world, actor["location_id"], {actor_id}):
            world.perceive(eid, wid, f"{actor['name']}放下{obj['name']}。")
        return {"ok": True, "event_id": eid}

    if isinstance(action, ExamineAction):
        obj = world.object(action.target)
        if obj and not obj["destroyed"]:
            here = (
                obj["location_id"] == actor["location_id"]
                or obj["holder_id"] == actor_id
            )
            if obj["hidden"] and obj["location_id"] == actor["location_id"]:
                world.cx.execute("UPDATE objects SET hidden=0 WHERE id=?", (obj["id"],))
                world.cx.commit()
                here = True
            if not here:
                return {"ok": False, "reason": "not_here"}
            eid = world.append_event(
                "examine",
                f"{actor['name']}察看{obj['name']}：{obj['description']}",
                actor_id=actor_id,
                payload={"object_id": obj["id"]},
            )
            world.perceive(eid, actor_id, f"你察看{obj['name']}。{obj['description']}")
            for wid in _witnesses(world, actor["location_id"], {actor_id}):
                world.perceive(eid, wid, f"{actor['name']}細看{obj['name']}。")
            return {"ok": True, "event_id": eid}
        if action.target == actor["location_id"] or action.target in (
            world.location(actor["location_id"])["name"].lower(),
            world.location(actor["location_id"])["name"],
        ):
            loc = world.location(actor["location_id"])
            hidden = world.cx.execute(
                "SELECT * FROM objects WHERE location_id=? AND hidden=1 AND destroyed=0",
                (loc["id"],),
            ).fetchall()
            found = ""
            if hidden:
                for h in hidden:
                    world.cx.execute(
                        "UPDATE objects SET hidden=0 WHERE id=?", (h["id"],)
                    )
                world.cx.commit()
                found = "此處藏有：" + "、".join(h["name"] for h in hidden) + "。"
            eid = world.append_event(
                "examine",
                f"{actor['name']}搜看{loc['name']}。{found}",
                actor_id=actor_id,
            )
            world.perceive(eid, actor_id, loc["description"] + found)
            return {"ok": True, "event_id": eid}
        return {"ok": False, "reason": "unknown_target"}

    if isinstance(action, WriteNoteAction):
        slug = re.sub(r"[^a-z0-9]+", "_", action.text.lower())[:24] or "zh"
        oid = f"note_{actor_id}_{world.day}_{world.scene}_{slug}"[:60]
        world.cx.execute(
            """INSERT OR REPLACE INTO objects(id, name, description, location_id, holder_id, hidden, destroyed)
               VALUES(?,?,?,?,?,0,0)""",
            (oid, "紙條", action.text[:500], None, actor_id),
        )
        world.cx.commit()
        eid = world.append_event(
            "write_note",
            f"{actor['name']}寫下一紙：「{action.text[:200]}」",
            actor_id=actor_id,
            payload={"object_id": oid},
        )
        world.perceive(eid, actor_id, f"你寫道：{action.text[:200]}")
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
            f"{actor['name']}夠不著{target_id}。",
            actor_id=actor["id"],
            target_id=target_id,
        )
        world.perceive(eid, actor["id"], "他們不在這裡。")
        return {"ok": False, "event_id": eid, "reason": "not_here"}

    weapon = _has_weapon(world, actor["id"])
    loc = actor["location_id"]
    if lethal:
        success = weapon or bool(target["injured"])
        if success:
            world.set_alive(target_id, False)
            eid = world.append_event(
                "kill",
                f"{actor['name']}殺死了{target['name']}。",
                actor_id=actor["id"],
                target_id=target_id,
                payload={"weapon": weapon},
            )
            world.perceive(eid, actor["id"], f"你殺死了{target['name']}。")
            for wid in _witnesses(world, loc, {actor["id"], target_id}):
                world.perceive(
                    eid, wid, f"你親眼見{actor['name']}殺死{target['name']}。"
                )
            world.bump_relationship(
                actor["id"], target_id, resentment=3, note="殺了對方"
            )
            return {"ok": True, "event_id": eid, "killed": True}
        world.set_injured(target_id, True)
        eid = world.append_event(
            "attempted_kill",
            f"{actor['name']}欲殺{target['name']}而不成；{target['name']}受傷。",
            actor_id=actor["id"],
            target_id=target_id,
        )
        world.perceive(
            eid, actor["id"], f"你未能殺死{target['name']}。對方受傷，且已曉得。"
        )
        world.perceive(eid, target_id, f"{actor['name']}要殺你。你受傷了。")
        for wid in _witnesses(world, loc, {actor["id"], target_id}):
            world.perceive(
                eid, wid, f"{actor['name']}對{target['name']}起了殺心，動手了。"
            )
        world.bump_relationship(
            target_id, actor["id"], trust=-5, resentment=5, note="要殺我"
        )
        return {
            "ok": True,
            "event_id": eid,
            "killed": False,
            "expect_reaction": target_id,
        }

    world.set_injured(target_id, True)
    eid = world.append_event(
        "attack",
        f"{actor['name']}襲擊{target['name']}。{target['name']}受傷。",
        actor_id=actor["id"],
        target_id=target_id,
    )
    world.perceive(eid, actor["id"], f"你襲擊{target['name']}。")
    world.perceive(eid, target_id, f"{actor['name']}襲擊你。你受傷了。")
    for wid in _witnesses(world, loc, {actor["id"], target_id}):
        world.perceive(eid, wid, f"{actor['name']}襲擊{target['name']}。")
    world.bump_relationship(
        target_id, actor["id"], trust=-3, resentment=3, note="襲擊了我"
    )
    return {"ok": True, "event_id": eid, "expect_reaction": target_id}
