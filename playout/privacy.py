"""Owner-only fields on setup and live snapshots."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


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
    out = deepcopy(snap)
    for act in out.get("actors") or []:
        act["secret"] = ""
    return out
