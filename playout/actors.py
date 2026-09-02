"""Actor turns: private context only. Goals update from perception, never from steer."""

from __future__ import annotations

from playout.canon import World
from playout.llm import LLM
from playout.memory import retrieve
from playout.models import ActorDecision, WaitAction, action_from_dict
from playout.referee import apply_action

ACTOR_SYSTEM = """You are a character in a living story simulation. Stay in persona. You are not helpful.
You only know what you perceived and wrote in your diary. You do not know other people's secrets unless you learned them.
You form goals yourself from what you have seen. Nobody may assign you a goal.

Return JSON:
{"thought": "private", "goal_update": null or a short new goal if your mind changed, "mood": "one word", "action": { ... }}

Action must be one of:
{"type":"move","to":"<location_id>"}
{"type":"speak_to","target":"<actor_id>","speech":"..."}
{"type":"take","object_id":"..."}
{"type":"drop","object_id":"..."}
{"type":"examine","target":"<object_id or location_id>"}
{"type":"wait"}
{"type":"write_note","text":"..."}
{"type":"attack","target":"<actor_id>"}
{"type":"kill","target":"<actor_id>"}

Rules:
- speak_to and attack/kill only if that person is HERE.
- move only to an adjacent location_id.
- Do not narrate the world. Choose one action.
- Violence is allowed if YOU decide it. Do not kill casually.
"""


def private_context(world: World, actor_id: str, extra: str = "") -> str:
    a = world.actor(actor_id)
    loc = world.location(a["location_id"])
    others = [x for x in world.actors_at(a["location_id"]) if x["id"] != actor_id]
    objs = world.visible_objects(a["location_id"])
    inv = world.inventory(actor_id)
    adj = []
    for aid in world.adjacent(a["location_id"]):
        dest = world.location(aid)
        adj.append(f"{aid} ({dest['name']})")
    rels = []
    for o in world.living_actors():
        if o["id"] == actor_id:
            continue
        r = world.relationship(actor_id, o["id"])
        if r:
            rels.append(f"{o['name']} ({o['id']}): trust {r['trust']}, resentment {r['resentment']}. {r['notes']}")
    query = extra or a["goal"]
    memories = retrieve(world, actor_id, query)
    perceptions = world.perceptions_for(actor_id, limit=12)
    reflections = world.reflections_for(actor_id, limit=3)
    people = ", ".join(f"{o['name']} ({o['id']})" + (" injured" if o["injured"] else "") for o in others) or "nobody"
    obj_s = ", ".join(f"{o['name']} [{o['id']}]" for o in objs) or "nothing obvious"
    inv_s = ", ".join(f"{o['name']} [{o['id']}]" for o in inv) or "empty"
    perc_s = "\n".join(f"- D{p['day']} {p['text']}" for p in perceptions[:10]) or "- (none yet)"
    mem_s = "\n".join(f"- {m}" for m in memories) or "- (blank diary)"
    ref_s = "\n".join(f"- {r['text']}" for r in reflections) or "- (none)"
    return f"""World: {world.meta('title')}. {world.meta('worldview')}
Time: day {world.day}, {world.time_label}. Weather: {world.meta('weather')}.
Clock: {world.meta('clock')}

YOU: {a['name']} ({a['id']})
Voice: {a['voice']}
Constitution (always true): {a['constitution']}
Deep want: {a['want']}
Your secret (you know this; others do not unless they learned it): {a['secret']}
Current goal (yours): {a['goal']}
Mood: {a['mood']}
Injured: {bool(a['injured'])}

HERE: {loc['name']} ({loc['id']}). {loc['description']}
Intact: {bool(loc['intact'])}
People here: {people}
Visible objects: {obj_s}
Your inventory: {inv_s}
Adjacent: {', '.join(adj) or 'none'}

Relationships:
{chr(10).join(rels) or '(thin)'}

Recent perceptions (what you actually saw/heard):
{perc_s}

Retrieved diary:
{mem_s}

Reflections:
{ref_s}

{extra}
"""


def _mock_decision(world: World, actor_id: str, extra: str) -> ActorDecision:
    a = world.actor(actor_id)
    loc = a["location_id"]
    others = [x for x in world.actors_at(loc) if x["id"] != actor_id]
    percs = world.perceptions_for(actor_id, limit=6)
    last = " ".join(p["text"] for p in percs[:3]).lower()

    if "tries to kill you" in last or "attacks you" in last:
        attacker = others[0]["id"] if others else None
        for p in percs:
            for o in others:
                if o["name"].split()[0].lower() in p["text"].lower() and (
                    "attack" in p["text"].lower() or "kill" in p["text"].lower()
                ):
                    attacker = o["id"]
        if attacker:
            return ActorDecision(thought="I have to stop them.", action=action_from_dict({"type": "attack", "target": attacker}))

    if others and ("says to you" in last):
        t = others[0]
        for o in others:
            if o["name"].split()[0] in last or o["id"] in last:
                t = o
        speech = {
            "lena": "I can't keep doing this. The debt, the storm — Tomas, we have to decide.",
            "tomas": "Once I have a boat we leave. Don't look at me like that.",
            "mara": "Someone took my husband's skiff. If you know anything, say it.",
            "ellis": "The bakery is mine when the storm hits unless you're paid. That's the paper.",
        }.get(actor_id, "We don't have time for this.")
        return ActorDecision(thought="They spoke to me.", action=action_from_dict({"type": "speak_to", "target": t["id"], "speech": speech}))

    hidden_here = world.cx.execute(
        "SELECT * FROM objects WHERE location_id=? AND hidden=1 AND destroyed=0", (loc,)
    ).fetchall()
    if hidden_here and actor_id in ("mara", "tomas") and loc in ("cliff_path", "mara_cottage"):
        return ActorDecision(thought="Something's off here.", action=action_from_dict({"type": "examine", "target": loc}))

    visible = world.visible_objects(loc)
    for obj in visible:
        if "letter" in obj["id"] or "knife" in obj["id"] or "cleaver" in obj["id"] or "skiff" in obj["id"]:
            if "letter" in obj["id"] or "skiff" in obj["id"]:
                return ActorDecision(thought="I need to see that.", action=action_from_dict({"type": "examine", "target": obj["id"]}))
            return ActorDecision(thought="I may need this.", action=action_from_dict({"type": "take", "object_id": obj["id"]}))

    # wander toward wants
    prefer = {
        "lena": ["bakery", "inn", "quay"],
        "tomas": ["cliff_path", "quay", "bakery"],
        "mara": ["boathouse", "quay", "cliff_path"],
        "ellis": ["inn", "bakery", "quay"],
    }.get(actor_id, [])
    adj = world.adjacent(loc)
    for dest in prefer:
        if dest in adj:
            return ActorDecision(thought="I should go.", action=action_from_dict({"type": "move", "to": dest}))
    if others:
        t = others[0]
        speech = {
            "lena": "Have you seen Tomas? The storm won't wait.",
            "tomas": "Keep your voice down. The boat business isn't settled.",
            "mara": "The skiff didn't walk off. Who was on the quay last night?",
            "ellis": "I'm a patient man until I'm not. Pay or sign.",
        }.get(actor_id, "Strange weather.")
        return ActorDecision(thought="Talk.", action=action_from_dict({"type": "speak_to", "target": t["id"], "speech": speech}))
    if adj:
        return ActorDecision(thought="Keep moving.", action=action_from_dict({"type": "move", "to": adj[0]}))
    return ActorDecision(thought="Nothing to do.", action=WaitAction())


def decide(world: World, llm: LLM, actor_id: str, extra: str = "") -> ActorDecision:
    ctx = private_context(world, actor_id, extra)
    if llm.mode == "mock":
        return _mock_decision(world, actor_id, extra)
    data = llm.complete_json(ACTOR_SYSTEM, ctx, strong=False)
    if not data:
        return _mock_decision(world, actor_id, extra)
    try:
        if "action" in data and isinstance(data["action"], dict):
            data["action"] = action_from_dict(data["action"])
        return ActorDecision.model_validate(data)
    except Exception:
        return ActorDecision(thought="confused", action=WaitAction())


def actor_turn(world: World, llm: LLM, actor_id: str, extra: str = "") -> dict:
    a = world.actor(actor_id)
    if not a["alive"]:
        return {"ok": False, "reason": "dead"}
    decision = decide(world, llm, actor_id, extra)
    if decision.goal_update:
        # Actor-owned goal change only.
        world.set_actor_goal(actor_id, decision.goal_update[:240])
    if decision.mood:
        world.set_actor_mood(actor_id, decision.mood[:40])
    result = apply_action(world, actor_id, decision.action)
    thought = decision.thought.strip()
    if thought:
        event_id = result.get("event_id")
        world.write_diary(
            actor_id,
            f"{thought} Then: {getattr(decision.action, 'type', 'act')}.",
            importance=6 if decision.action.type in ("attack", "kill", "examine") else 4,
            event_id=event_id,
        )
    diaries = world.diary_for(actor_id, limit=6)
    if len(diaries) >= 4 and world.scene % 2 == 0:
        if llm.mode == "mock":
            world.write_reflection(actor_id, f"I still want: {world.actor(actor_id)['goal']}")
        else:
            blob = "\n".join(d["text"] for d in diaries[:6])
            ref = llm.complete(
                "Summarize this character's private insight in 2 sentences, in their voice. No new facts.",
                blob,
                strong=False,
            )
            if ref:
                world.write_reflection(actor_id, ref[:500])
    result["thought"] = thought
    result["action"] = decision.action.model_dump()
    return result
