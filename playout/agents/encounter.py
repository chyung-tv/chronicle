"""Co-located encounter hold: B answers inside A's tool, no nested hold."""

from __future__ import annotations

import json
from typing import Any

from playout.canon import World
from playout.llm import LLM

ENCOUNTER_EXTRA = (
    "有人剛對你說話，或剛動手。你須反應。可以開口、還手、等候（不理）、"
    "取物、察看，或離開。這不是你自己的時辰；只動一次。"
    "不可再開一場對持，也不可等對方立刻再答。"
)


def hold_encounter(
    world: World,
    llm: LLM,
    initiator_id: str,
    counterpart_id: str,
    opening: dict[str, Any],
) -> dict[str, Any]:
    """Run counterpart once against the live world; return what the initiator perceived."""
    opening_eid = int(opening.get("event_id") or 0)
    initiator = world.actor(initiator_id)
    try:
        other = world.actor(counterpart_id)
    except Exception:
        return {"counterpart": counterpart_id, "result": {"ok": False, "reason": "unknown_target"}, "perceived": []}
    if not other["alive"] or other["location_id"] != initiator["location_id"]:
        return {
            "counterpart": counterpart_id,
            "result": {"ok": False, "reason": "not_here"},
            "perceived": [],
        }

    world.set_meta(
        "encounter",
        json.dumps(
            {
                "initiator": initiator_id,
                "counterpart": counterpart_id,
                "active": True,
            },
            ensure_ascii=False,
        ),
    )
    world.cx.commit()
    world.set_activity(
        "thinking",
        actor=counterpart_id,
        detail=f"{other['name']}正在對答",
    )

    from playout.agents.actor import ActorAgent, perceptions_since

    extra = (
        ENCOUNTER_EXTRA
        + f"\n對方是{initiator['name']}（{initiator_id}）。"
        + (f"\n方才：{opening.get('summary', '')}" if opening.get("summary") else "")
    )
    result = ActorAgent(llm).run(
        world,
        counterpart_id,
        extra=extra,
        in_encounter=True,
        allow_encounter=False,
        mutate_budget=1,
    )
    world.set_meta("encounter", "")
    world.cx.commit()

    perceived = perceptions_since(world, initiator_id, opening_eid) if opening_eid else []
    return {
        "counterpart": counterpart_id,
        "result": result,
        "perceived": perceived,
    }
