"""Day run sequence: shuffled actor bag, random event insertions, persisted on World."""

from __future__ import annotations

import random
from typing import Any

from playout.canon import World

MAX_TURNS_PER_DAY = 8


def living_ids(world: World) -> list[str]:
    return [a["id"] for a in world.living_actors()]


def plan_actor_bag(
    actor_ids: list[str],
    rng: random.Random,
    *,
    lo: int | None = None,
    hi: int | None = None,
) -> list[str]:
    n = len(actor_ids)
    if n == 0:
        return []
    lo_n = n if lo is None else max(n, lo)
    hi_n = n if hi is None else hi
    hi_n = max(lo_n, min(MAX_TURNS_PER_DAY, hi_n))
    length = rng.randint(lo_n, hi_n)
    bag = list(actor_ids)
    while len(bag) < length:
        bag.append(rng.choice(actor_ids))
    rng.shuffle(bag)
    return bag


def insert_event_slots(
    actor_slots: list[dict[str, Any]],
    injections: list[dict[str, Any]],
    rng: random.Random,
) -> list[dict[str, Any]]:
    slots = [dict(s) for s in actor_slots]
    for inj in injections:
        idx = rng.randint(0, len(slots))
        event = dict(inj)
        event["kind"] = "event"
        event["status"] = event.get("status", "pending")
        slots.insert(idx, event)
    return slots


def build_day_plan(
    world: World,
        injections: list[dict[str, Any]],
    rng: random.Random,
) -> dict[str, Any]:
    ids = living_ids(world)
    lo = world.turns_per_day_min
    hi = world.turns_per_day_max
    bag = plan_actor_bag(ids, rng, lo=lo, hi=hi)
    actor_slots = [
        {"kind": "actor", "actor_id": aid, "status": "pending"} for aid in bag
    ]
    slots = insert_event_slots(actor_slots, injections, rng)
    return {
        "day": world.day,
        "length": len(bag),
        "cursor": 0,
        "steer": {
            "done": True,
            "intent_ids": [
                i.get("intent_id") for i in injections if i.get("source") == "steer"
            ],
        },
        "slots": slots,
    }


def scheduled_steer_keys(plan: dict[str, Any] | None) -> set[tuple[Any, Any]]:
    if not plan:
        return set()
    keys: set[tuple[Any, Any]] = set()
    for slot in plan.get("slots") or []:
        if slot.get("kind") == "event" and slot.get("source") == "steer":
            keys.add((slot.get("intent_id"), slot.get("rung_id")))
    return keys


def insert_remaining_event(
    plan: dict[str, Any], slot: dict[str, Any], rng: random.Random
) -> dict[str, Any]:
    """Park a new event in a gap at or after the current cursor."""
    cursor = int(plan.get("cursor") or 0)
    slots = list(plan.get("slots") or [])
    idx = rng.randint(cursor, len(slots))
    event = dict(slot)
    event["kind"] = "event"
    event["status"] = "pending"
    slots.insert(idx, event)
    plan["slots"] = slots
    return plan
