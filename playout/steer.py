"""Steer: future-facing intents become campaigns. Never retcon. Never puppet the climax."""

from __future__ import annotations

import json
import re
from typing import Any

from playout.canon import World
from playout.llm import LLM
from playout.models import Patch, SteerCampaign, SteerRung, StorytellerPlan
from playout.storyteller import apply_patches

STEER_SYSTEM = """You are a drama manager for a sealed-canon simulation.
The human names a FUTURE outcome they want to become likely, e.g. "Lena should kill Ellis".
You invent a campaign of NEW stimuli (motive, means, opportunity, escalation).
You do NOT:
- rewrite anyone's memory or diary
- assign goals ("Lena decides to murder")
- insert the climax action (no kill patch, no forcing an attack)
- invent a fake past ("she now remembers he killed her brother" unless that seed already exists in the character secret and is unrevealed)

You MAY:
- add objects, rumors, environmental pulls, reveal hidden design-time objects
- injure nobody as a shortcut to the climax
- use existing wants, secrets, and grudges

Return JSON:
{
  "summary": "short",
  "success_predicates": ["kill:lena->ellis"],
  "failure_predicates": ["dead:lena", "kill:ellis->lena"],
  "rungs": [
    {"id":"motive","kind":"motive","status":"pending","injection":{"summary":"...","patches":[...]}},
    {"id":"means","kind":"means","status":"pending","injection":{"summary":"...","patches":[...]}},
    {"id":"opportunity","kind":"opportunity","status":"pending","injection":{"summary":"...","patches":[...]}},
    {"id":"escalation","kind":"escalation","status":"pending","injection":{"summary":"...","patches":[...]} }
  ]
}

Patch ops: rumor, broadcast, add_object, reveal_object, move_actor, describe_location, set_weather.
Do not use kill_actor or injure_actor in a steer campaign.
"""


def _index_actors(world: World) -> list[dict]:
    return [
        {
            "id": a["id"],
            "name": a["name"],
            "want": a["want"],
            "secret": a["secret"],
            "location": a["location_id"],
            "alive": bool(a["alive"]),
        }
        for a in world.cx.execute("SELECT * FROM actors")
    ]


def _match_actor(text: str, actors: list[dict]) -> str | None:
    t = text.lower()
    for a in actors:
        if a["id"] in t or a["name"].lower() in t or a["name"].split()[0].lower() in t:
            return a["id"]
    return None


def _parse_pair(text: str, actors: list[dict]) -> tuple[str | None, str | None]:
    hits: list[tuple[int, str]] = []
    for a in actors:
        labels = {a["id"], a["name"], a["name"].split()[0]}
        for label in labels:
            m = re.search(rf"\b{re.escape(label)}\b", text, re.I)
            if m:
                hits.append((m.start(), a["id"]))
                break
    hits.sort()
    ids: list[str] = []
    seen: set[str] = set()
    for _, aid in hits:
        if aid not in seen:
            seen.add(aid)
            ids.append(aid)
    a_id = ids[0] if ids else None
    b_id = ids[1] if len(ids) > 1 else None
    return a_id, b_id


def _heuristic_campaign(world: World, text: str) -> SteerCampaign:
    actors = _index_actors(world)
    a_id, b_id = _parse_pair(text, actors)
    if not a_id:
        a_id = actors[0]["id"]
    if not b_id:
        b_id = next((x["id"] for x in actors if x["id"] != a_id), actors[-1]["id"])
    a = world.actor(a_id)
    b = world.actor(b_id)
    # Prefer existing seeds
    seed_letter = world.object("affair_letter")
    motive_patches: list[Patch]
    if seed_letter and seed_letter["hidden"]:
        motive_patches = []
        if a["location_id"] != "mara_cottage":
            motive_patches.append(
                Patch(
                    op="move_actor",
                    actor_id=a_id,
                    location_id="mara_cottage",
                    detail="A boy on the quay says Mara left her door unlatched and papers on the table.",
                )
            )
        motive_patches.extend(
            [
                Patch(
                    op="reveal_object",
                    object_id="affair_letter",
                    detail=f"On the table, a letter in Mara's hand names {b['name']}.",
                ),
                Patch(
                    op="rumor",
                    actor_ids=[a_id],
                    detail=f"You read a letter that names {b['name']}. This is paper on the table now, not a memory you always had.",
                ),
            ]
        )
    else:
        motive_patches = [
            Patch(
                op="add_object",
                object_id=f"steer_proof_{a_id}_{b_id}",
                name="torn account page",
                location_id=a["location_id"],
                detail=f"Figures in {b['name']}'s hand showing how they mean to take what {a['name']} loves.",
            ),
            Patch(
                op="rumor",
                actor_ids=[a_id],
                detail=f"You find proof that {b['name']} is moving against you. Not a memory — paper, now, in your hands if you take it.",
            ),
        ]
    means = [
        Patch(
            op="add_object",
            object_id=f"steer_means_{a_id}",
            name="fish knife",
            location_id=a["location_id"],
            detail="A long fish knife, recently sharpened. Nobody is watching it.",
        ),
        Patch(
            op="rumor",
            actor_ids=[a_id],
            detail="A knife lies where you could take it. You do not have to. It is simply there.",
        ),
    ]
    # isolate: park others elsewhere, put A and B together
    isolate_loc = b["location_id"]
    opp: list[Patch] = [
        Patch(
            op="move_actor",
            actor_id=a_id,
            location_id=isolate_loc,
            detail=f"You hear {b['name']} is alone. The storm covers sound.",
        )
    ]
    for other in world.living_actors():
        if other["id"] in (a_id, b_id):
            continue
        if other["location_id"] == isolate_loc:
            refuge = next((x for x in world.adjacent(isolate_loc) if x), other["location_id"])
            opp.append(
                Patch(
                    op="move_actor",
                    actor_id=other["id"],
                    location_id=refuge,
                    detail="A shout from elsewhere pulls you away.",
                )
            )
    esc = [
        Patch(
            op="rumor",
            actor_ids=[a_id],
            detail=f"Word reaches you that {b['name']} will move against you before the storm. Waiting is another kind of death.",
        ),
        Patch(
            op="rumor",
            actor_ids=[b_id],
            detail=f"You hear {a['name']} has been asking for you. They looked wrong. Watch the door.",
        ),
    ]
    return SteerCampaign(
        summary=f"Make it possible that {a['name']} harms {b['name']}, without doing it for them.",
        success_predicates=[f"kill:{a_id}->{b_id}"],
        failure_predicates=[f"dead:{a_id}", f"kill:{b_id}->{a_id}"],
        rungs=[
            SteerRung(id="motive", kind="motive", injection=StorytellerPlan(summary=f"Motive reaches {a['name']}.", patches=motive_patches)),
            SteerRung(id="means", kind="means", injection=StorytellerPlan(summary=f"A weapon is available to {a['name']}.", patches=means)),
            SteerRung(id="opportunity", kind="opportunity", injection=StorytellerPlan(summary=f"{a['name']} and {b['name']} may be alone.", patches=opp)),
            SteerRung(id="escalation", kind="escalation", injection=StorytellerPlan(summary="Pressure rises.", patches=esc)),
        ],
    )


def _eval_predicates(world: World, preds: list[str]) -> bool:
    events = world.all_events()
    dead = {a["id"] for a in world.cx.execute("SELECT id FROM actors WHERE alive=0")}
    for p in preds:
        p = p.strip()
        if p.startswith("dead:"):
            if p.split(":", 1)[1] in dead:
                return True
        elif p.startswith("kill:"):
            rest = p.split(":", 1)[1]
            if "->" in rest:
                src, dst = rest.split("->", 1)
                for e in events:
                    if e["kind"] in ("kill",) and e["actor_id"] == src and e["target_id"] == dst:
                        return True
        elif p.startswith("attempt:"):
            rest = p.split(":", 1)[1]
            src, dst = rest.split("->", 1)
            for e in events:
                if e["kind"] == "attempted_kill" and e["actor_id"] == src and e["target_id"] == dst:
                    return True
        elif p.startswith("injured:"):
            aid = p.split(":", 1)[1]
            row = world.actor(aid)
            if row["injured"]:
                return True
    return False


def _forbidden_ops(campaign: SteerCampaign) -> SteerCampaign:
    allowed = {"rumor", "broadcast", "add_object", "reveal_object", "move_actor", "describe_location", "set_weather"}
    for rung in campaign.rungs:
        rung.injection.patches = [p for p in rung.injection.patches if p.op in allowed]
    return campaign


def submit_intent(world: World, llm: LLM, text: str) -> dict[str, Any]:
    actors = _index_actors(world)
    locs = [{"id": l["id"], "name": l["name"]} for l in world.cx.execute("SELECT id,name FROM locations")]
    hidden = [
        {"id": o["id"], "name": o["name"], "location": o["location_id"]}
        for o in world.cx.execute("SELECT * FROM objects WHERE hidden=1 AND destroyed=0")
    ]
    user = f"Intent: {text}\nDay {world.day} {world.time_label}\nActors: {json.dumps(actors)}\nLocations: {locs}\nUnrevealed objects: {hidden}"
    campaign: SteerCampaign
    if llm.mode == "live":
        data = llm.complete_json(STEER_SYSTEM, user, strong=True)
        try:
            campaign = _forbidden_ops(SteerCampaign.model_validate(data))
            if not campaign.rungs:
                campaign = _heuristic_campaign(world, text)
        except Exception:
            campaign = _heuristic_campaign(world, text)
    else:
        campaign = _heuristic_campaign(world, text)
    campaign = _forbidden_ops(campaign)
    cur = world.cx.execute(
        "INSERT INTO steer_intents(text, status, campaign, created_day, created_scene) VALUES(?,?,?,?,?)",
        (text, "brewing", campaign.model_dump_json(), world.day, world.scene),
    )
    world.cx.commit()
    return {"id": int(cur.lastrowid), "status": "brewing", "campaign": campaign.model_dump()}


def _save_campaign(world: World, intent_id: int, status: str, campaign: SteerCampaign) -> None:
    world.cx.execute(
        "UPDATE steer_intents SET status=?, campaign=? WHERE id=?",
        (status, campaign.model_dump_json(), intent_id),
    )
    world.cx.commit()


def tick_intents(world: World) -> list[dict[str, Any]]:
    """After a scene: resolve or inject the next rung. One injection per intent per tick."""
    out = []
    rows = list(
        world.cx.execute("SELECT * FROM steer_intents WHERE status IN ('brewing','attempted')")
    )
    for row in rows:
        campaign = SteerCampaign.model_validate(json.loads(row["campaign"]))
        if _eval_predicates(world, campaign.success_predicates):
            _save_campaign(world, row["id"], "succeeded", campaign)
            out.append({"id": row["id"], "status": "succeeded"})
            continue
        if _eval_predicates(world, campaign.failure_predicates):
            _save_campaign(world, row["id"], "failed", campaign)
            out.append({"id": row["id"], "status": "failed"})
            continue
        if _eval_predicates(world, [p.replace("kill:", "attempt:") for p in campaign.success_predicates if p.startswith("kill:")]):
            if row["status"] != "attempted":
                _save_campaign(world, row["id"], "attempted", campaign)
        pending = next((r for r in campaign.rungs if r.status == "pending"), None)
        if pending:
            apply_patches(world, pending.injection, kind=f"steer_{pending.kind}")
            pending.status = "injected"
            status = "attempted" if row["status"] == "attempted" else "brewing"
            _save_campaign(world, row["id"], status, campaign)
            out.append({"id": row["id"], "status": status, "injected": pending.id})
        else:
            out.append({"id": row["id"], "status": row["status"], "injected": None})
    return out
