"""Co-located encounter hold: B answers inside A's interact, then one referee judgment."""

from __future__ import annotations

from typing import Any

from playout.canon import World
from playout.llm import LLM

ENCOUNTER_EXTRA = (
    "有人剛要與你互動。你須用 interact 寫出你此刻試圖做的事"
    "（開口、還手、搶物、離開某地等），或 wait 不理。"
    "這不是你自己的時辰；只動一次。不可再開對持。"
    "不要用 move 工具；若要走，把目的地寫進 interact，由裁判判定。"
)


async def hold_encounter(
    world: World,
    llm: LLM,
    initiator_id: str,
    counterpart_id: str,
    a_text: str,
) -> dict[str, Any]:
    """Run counterpart once against the live world; referee both attempts; return A's view."""
    initiator = world.actor(initiator_id)
    try:
        other = world.actor(counterpart_id)
    except Exception:
        return {
            "counterpart": counterpart_id,
            "result": {"ok": False, "reason": "unknown_target"},
            "perceived": [],
        }
    if not other["alive"] or other["location_id"] != initiator["location_id"]:
        return {
            "counterpart": counterpart_id,
            "result": {"ok": False, "reason": "not_here"},
            "perceived": [],
        }

    world.set_encounter(
        {
            "initiator": initiator_id,
            "counterpart": counterpart_id,
            "a_text": a_text,
            "b_text": None,
            "active": True,
            "resolved": False,
        }
    )
    world.set_activity(
        "thinking",
        actor=counterpart_id,
        detail=f"{other['name']}正在對答",
    )

    from playout.agents.actor import ActorAgent, perceptions_since
    from playout.agents.referee import RefereeAgent

    extra = (
        ENCOUNTER_EXTRA
        + f"\n對方是{initiator['name']}（{initiator_id}）。"
        + f"\n對方試圖：{a_text}"
    )
    before = world.cx.execute("SELECT COALESCE(MAX(id),0) AS m FROM events").fetchone()
    before_id = int(before["m"]) if before else 0

    result = await ActorAgent(llm).run_async(
        world,
        counterpart_id,
        extra=extra,
        in_encounter=True,
        allow_encounter=False,
        mutate_budget=1,
    )

    meta = world.get_encounter() or {}
    verdict = meta.get("verdict") if meta.get("resolved") else None
    if not meta.get("resolved"):
        world.set_activity(
            "thinking", actor="referee", detail="裁判正在判定"
        )
        verdict = await RefereeAgent(llm).judge(
            world,
            a_id=initiator_id,
            a_text=a_text,
            b_id=counterpart_id,
            b_text=meta.get("b_text"),
        )
    world.set_encounter(None)

    eid = int((verdict or {}).get("event_id") or before_id + 1)
    perceived = perceptions_since(world, initiator_id, eid) if eid else []
    return {
        "counterpart": counterpart_id,
        "result": result,
        "perceived": perceived,
        "verdict": verdict,
        "event_id": (verdict or {}).get("event_id"),
        "summary": (verdict or {}).get("summary"),
        "ok": bool((verdict or {}).get("ok", True)),
    }
