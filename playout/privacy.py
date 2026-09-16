"""Audience vs owner fields on setup and live snapshots.

Readers may inspect diaries, goals, and moods. Secrets, steer rungs,
and other god-rail chrome stay owner-only.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

STEER_EVENT_KINDS = frozenset(
    {
        "steer_motive",
        "steer_means",
        "steer_opportunity",
        "steer_escalation",
    }
)


def is_public_live(visibility: str, status: str) -> bool:
    return visibility == "public" and status == "live"


def redact_setup(setup: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(setup)
    for act in out.get("actors") or []:
        act["secret"] = ""
    for obj in out.get("objects") or []:
        if obj.get("hidden"):
            obj["description"] = ""
    for rel in out.get("relationships") or []:
        rel["notes"] = ""
    return out


def redact_sketch(sketch: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(sketch)
    for act in out.get("actors") or []:
        act["note"] = ""
    return out


def redact_snapshot(snap: dict[str, Any]) -> dict[str, Any]:
    """Strip owner-only fields. Keep chapters, public tape, map, cast, diaries, goals, moods."""
    out = deepcopy(snap)
    for act in out.get("actors") or []:
        act["secret"] = ""
    out["intents"] = []
    out["day_plan"] = None
    events = [
        e
        for e in (out.get("events") or [])
        if (e.get("kind") or "") not in STEER_EVENT_KINDS
    ]
    out["events"] = events
    return out
