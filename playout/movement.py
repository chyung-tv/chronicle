"""Movement resolver: the only code path that changes actors.location_id."""

from __future__ import annotations

from typing import TYPE_CHECKING

from playout.models import MoveIntent, MoveResolution

if TYPE_CHECKING:
    from playout.canon import World


def evaluate_move(world: World, intent: MoveIntent) -> MoveResolution:
    """Check hop legality. Does not mutate world."""
    try:
        actor = world.actor(intent.actor_id)
    except Exception:
        return MoveResolution(
            ok=False,
            actor_id=intent.actor_id,
            from_id="",
            kind=intent.kind,
            reason="unknown_actor",
            summary="無人可走。",
        )
    here = actor["location_id"]
    if not actor["alive"]:
        return MoveResolution(
            ok=False,
            actor_id=intent.actor_id,
            from_id=here,
            kind=intent.kind,
            reason="dead",
            summary=f"{actor['name']}已不能走。",
            self_perception="你走不動了。",
        )

    dest_id = intent.to
    dest_name = dest_id
    if intent.kind == "evacuate" and not dest_id:
        intact = world.exits(here)
        dest_id = intact[0].id if intact else here
    try:
        dest = world.location(dest_id)
        dest_name = dest["name"]
    except Exception:
        return MoveResolution(
            ok=False,
            actor_id=intent.actor_id,
            from_id=here,
            to_id=dest_id,
            dest_name=dest_name,
            kind=intent.kind,
            reason="unknown_dest",
            summary=f"{actor['name']}無法由此前往{dest_id}。",
            self_perception="那地方並不相鄰。",
        )

    if dest_id == here:
        reason = "no_refuge" if intent.kind == "evacuate" else "already_here"
        return MoveResolution(
            ok=False,
            actor_id=intent.actor_id,
            from_id=here,
            to_id=dest_id,
            dest_name=dest_name,
            kind=intent.kind,
            reason=reason,
            summary=f"{actor['name']}仍在{dest_name}。",
            self_perception="你還在原地。",
        )

    allowed = {e.id for e in world.exits(here)}
    if dest_id not in allowed:
        if intent.kind == "evacuate":
            return MoveResolution(
                ok=False,
                actor_id=intent.actor_id,
                from_id=here,
                to_id=dest_id,
                dest_name=dest_name,
                kind=intent.kind,
                reason="no_refuge",
                summary=f"{actor['name']}無路可逃。",
                self_perception="無路可走。",
            )
        if dest_id not in world.adjacent(here):
            reason, self_p = "not_adjacent", "那地方並不相鄰。"
            summary = f"{actor['name']}無法由此前往{dest_name}。"
        else:
            reason, self_p = "ruined", f"{dest_name}已毀。"
            summary = f"{actor['name']}見{dest_name}已毀，無路可入。"
        return MoveResolution(
            ok=False,
            actor_id=intent.actor_id,
            from_id=here,
            to_id=dest_id,
            dest_name=dest_name,
            kind=intent.kind,
            reason=reason,
            summary=summary,
            self_perception=self_p,
        )

    if intent.kind == "forced":
        summary = f"{actor['name']}被引向{dest_name}。"
        self_p = f"你被引向{dest_name}。{dest['description']}"
    elif intent.kind == "evacuate":
        summary = f"{actor['name']}自危地逃至{dest_name}。"
        self_p = f"你逃到{dest_name}。{dest['description']}"
    else:
        summary = f"{actor['name']}前往{dest_name}。"
        self_p = f"你到了{dest_name}。{dest['description']}"

    return MoveResolution(
        ok=True,
        actor_id=intent.actor_id,
        from_id=here,
        to_id=dest_id,
        dest_name=dest_name,
        kind=intent.kind,
        summary=summary,
        self_perception=self_p,
        leave_perception=f"{actor['name']}往{dest_name}去了。",
        arrive_perception=f"{actor['name']}來了。",
    )


def write_move_perceptions(world: World, event_id: int, res: MoveResolution) -> None:
    if not res.ok:
        if res.self_perception:
            world.perceive(event_id, res.actor_id, res.self_perception)
        return
    dest_id = res.to_id
    if not dest_id:
        return
    for wid in _witnesses(world, res.from_id, {res.actor_id}):
        world.perceive(event_id, wid, res.leave_perception)
    world.perceive(event_id, res.actor_id, res.self_perception)
    for wid in _witnesses(world, dest_id, {res.actor_id}):
        world.perceive(event_id, wid, res.arrive_perception)


def apply_move(
    world: World,
    intent: MoveIntent,
    *,
    record_event: bool = True,
    event_id: int | None = None,
    detail: str | None = None,
) -> MoveResolution:
    """Mutate location_id if legal. Optionally seal a move/failed_move event."""
    res = evaluate_move(world, intent)
    if res.ok and detail:
        res.self_perception = detail
    if res.ok and res.to_id:
        world.set_actor_location(intent.actor_id, res.to_id)

    if event_id is not None:
        write_move_perceptions(world, event_id, res)
        res.event_id = event_id
        return res

    if not record_event:
        return res

    kind = "failed_move"
    if res.ok:
        kind = "forced_move" if intent.kind == "forced" else "move"
    eid = world.append_event(
        kind,
        res.summary,
        actor_id=intent.actor_id,
        payload={
            "from": res.from_id,
            "to": res.to_id,
            "reason": res.reason,
            "kind": intent.kind,
        },
    )
    write_move_perceptions(world, eid, res)
    res.event_id = eid
    return res


def _witnesses(world: World, loc_id: str, exclude: set[str]) -> list[str]:
    if not loc_id:
        return []
    return [a["id"] for a in world.actors_at(loc_id) if a["id"] not in exclude]
