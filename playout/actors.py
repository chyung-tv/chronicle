"""Actor turns: private context only. Goals update from perception, never from steer."""

from __future__ import annotations

from playout.canon import World
from playout.llm import LLM
from playout.memory import retrieve
from playout.models import ActorDecision, WaitAction, action_from_dict
from playout.referee import apply_action
from playout.zh import with_prose

ACTOR_SYSTEM = with_prose("""你是活在故事裡的人物，須守住人格，不是助手。
你只知道自己感知過、寫進日記的事。別人的秘密，除非你已得知，否則你不知道。
目標由你自己從所見所聞長出。誰也不能替你派一個目標。

只回傳 JSON：
{"thought": "私心，繁體中文", "goal_update": null 或一句新目標, "mood": "一字心境", "action": { ... }}

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

規則：
- speak_to、attack、kill 僅當對方在此。
- move 只能去相鄰的 location_id。
- 不要敘述世界。只選一個行動。
- 若你自己決定，可以動武。勿輕易殺人。
speech、thought、goal_update 一律繁體中文。
""")


def private_context(world: World, actor_id: str, extra: str = "") -> str:
    a = world.actor(actor_id)
    loc = world.location(a["location_id"])
    others = [x for x in world.actors_at(a["location_id"]) if x["id"] != actor_id]
    objs = world.visible_objects(a["location_id"])
    inv = world.inventory(actor_id)
    adj = []
    for aid in world.adjacent(a["location_id"]):
        dest = world.location(aid)
        adj.append(f"{aid}（{dest['name']}）")
    rels = []
    for o in world.living_actors():
        if o["id"] == actor_id:
            continue
        r = world.relationship(actor_id, o["id"])
        if r:
            rels.append(
                f"{o['name']}（{o['id']}）：信 {r['trust']}，怨 {r['resentment']}。{r['notes']}"
            )
    query = extra or a["goal"]
    memories = retrieve(world, actor_id, query)
    perceptions = world.perceptions_for(actor_id, limit=12)
    reflections = world.reflections_for(actor_id, limit=3)
    people = (
        "、".join(
            f"{o['name']}（{o['id']}）" + ("，帶傷" if o["injured"] else "")
            for o in others
        )
        or "無人"
    )
    obj_s = "、".join(f"{o['name']} [{o['id']}]" for o in objs) or "眼前無物"
    inv_s = "、".join(f"{o['name']} [{o['id']}]" for o in inv) or "空手"
    perc_s = (
        "\n".join(f"- 第{p['day']}日 {p['text']}" for p in perceptions[:10])
        or "- （尚無）"
    )
    mem_s = "\n".join(f"- {m}" for m in memories) or "- （日記空白）"
    ref_s = "\n".join(f"- {r['text']}" for r in reflections) or "- （無）"
    return f"""世界：{world.meta("title")}。{world.meta("worldview")}
時辰：第{world.day}日，{world.time_label}。天色：{world.meta("weather")}。
期限：{world.meta("clock")}

你是：{a["name"]}（{a["id"]}）
口吻：{a["voice"]}
本性（不變）：{a["constitution"]}
深願：{a["want"]}
你的秘密（他人不知，除非已聞）：{a["secret"]}
眼前之願（屬你）：{a["goal"]}
心境：{a["mood"]}
帶傷：{bool(a["injured"])}

此地：{loc["name"]}（{loc["id"]}）。{loc["description"]}
完好：{bool(loc["intact"])}
在場：{people}
可見之物：{obj_s}
隨身：{inv_s}
相鄰：{", ".join(adj) or "無"}

關係：
{chr(10).join(rels) or "（淡）"}

近時感知（你真正見聞）：
{perc_s}

憶起的日記：
{mem_s}

省思：
{ref_s}

{extra}
"""


def _mock_decision(world: World, actor_id: str, extra: str) -> ActorDecision:
    loc = world.actor(actor_id)["location_id"]
    others = [x for x in world.actors_at(loc) if x["id"] != actor_id]
    percs = world.perceptions_for(actor_id, limit=6)
    last = " ".join(p["text"] for p in percs[:3])
    last_l = last.lower()

    if (
        "要殺你" in last
        or "襲擊你" in last
        or "tries to kill you" in last_l
        or "attacks you" in last_l
    ):
        attacker = others[0]["id"] if others else None
        for p in percs:
            for o in others:
                name = o["name"]
                blob = p["text"]
                if (name in blob or o["id"] in blob.lower()) and (
                    "襲擊" in blob
                    or "殺" in blob
                    or "attack" in blob.lower()
                    or "kill" in blob.lower()
                ):
                    attacker = o["id"]
        if attacker:
            return ActorDecision(
                thought="不能不還手。",
                action=action_from_dict({"type": "attack", "target": attacker}),
            )

    if others and ("對你道" in last or "says to you" in last_l):
        t = others[0]
        for o in others:
            if o["name"] in last or o["id"] in last_l:
                t = o
        speech = {
            "lena": "不能再這樣。債、風——渡，我們得定下來。",
            "tomas": "有船就走。別那樣看我。",
            "mara": "有人拿走亡夫的舢板。你若曉得，說。",
            "ellis": "風一來，舖子就是我的，除非你還清。紙上寫著。",
        }.get(actor_id, "沒有時間了。")
        return ActorDecision(
            thought="有人對我說話。",
            action=action_from_dict({
                "type": "speak_to",
                "target": t["id"],
                "speech": speech,
            }),
        )

    hidden_here = world.cx.execute(
        "SELECT * FROM objects WHERE location_id=? AND hidden=1 AND destroyed=0", (loc,)
    ).fetchall()
    if (
        hidden_here
        and actor_id in ("mara", "tomas")
        and loc in ("cliff_path", "mara_cottage")
    ):
        return ActorDecision(
            thought="此處不妥。",
            action=action_from_dict({"type": "examine", "target": loc}),
        )

    visible = world.visible_objects(loc)
    for obj in visible:
        if (
            "letter" in obj["id"]
            or "knife" in obj["id"]
            or "cleaver" in obj["id"]
            or "skiff" in obj["id"]
        ):
            if "letter" in obj["id"] or "skiff" in obj["id"]:
                return ActorDecision(
                    thought="得看清楚。",
                    action=action_from_dict({"type": "examine", "target": obj["id"]}),
                )
            return ActorDecision(
                thought="或許用得著。",
                action=action_from_dict({"type": "take", "object_id": obj["id"]}),
            )

    prefer = {
        "lena": ["bakery", "inn", "quay"],
        "tomas": ["cliff_path", "quay", "bakery"],
        "mara": ["boathouse", "quay", "cliff_path"],
        "ellis": ["inn", "bakery", "quay"],
    }.get(actor_id, [])
    adj = world.adjacent(loc)
    for dest in prefer:
        if dest in adj:
            return ActorDecision(
                thought="該走了。",
                action=action_from_dict({"type": "move", "to": dest}),
            )
    if others:
        t = others[0]
        speech = {
            "lena": "你見著張渡沒有？風不等人。",
            "tomas": "聲小些。船的事還沒完。",
            "mara": "舢板不會自己走。昨夜碼頭是誰？",
            "ellis": "我有耐性，直到沒有。還錢，或者簽字。",
        }.get(actor_id, "天色怪。")
        return ActorDecision(
            thought="開口。",
            action=action_from_dict({
                "type": "speak_to",
                "target": t["id"],
                "speech": speech,
            }),
        )
    if adj:
        return ActorDecision(
            thought="再走一步。",
            action=action_from_dict({"type": "move", "to": adj[0]}),
        )
    return ActorDecision(thought="無事可做。", action=WaitAction())


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
        return ActorDecision(thought="心亂。", action=WaitAction())


def actor_turn(world: World, llm: LLM, actor_id: str, extra: str = "") -> dict:
    a = world.actor(actor_id)
    if not a["alive"]:
        return {"ok": False, "reason": "dead"}
    decision = decide(world, llm, actor_id, extra)
    if decision.goal_update:
        world.set_actor_goal(actor_id, decision.goal_update[:240])
    if decision.mood:
        world.set_actor_mood(actor_id, decision.mood[:40])
    result = apply_action(world, actor_id, decision.action)
    thought = decision.thought.strip()
    if thought:
        event_id = result.get("event_id")
        world.write_diary(
            actor_id,
            f"{thought} 於是：{getattr(decision.action, 'type', 'act')}。",
            importance=6
            if decision.action.type in ("attack", "kill", "examine")
            else 4,
            event_id=event_id,
        )
    diaries = world.diary_for(actor_id, limit=6)
    if len(diaries) >= 4 and world.scene % 2 == 0:
        if llm.mode == "mock":
            world.write_reflection(
                actor_id, f"我仍想要：{world.actor(actor_id)['goal']}"
            )
        else:
            blob = "\n".join(d["text"] for d in diaries[:6])
            ref = llm.complete(
                with_prose("用這人的口吻，兩句話寫出私心。不准添新事實。"),
                blob,
                strong=False,
            )
            if ref:
                world.write_reflection(actor_id, ref[:500])
    result["thought"] = thought
    result["action"] = decision.action.model_dump()
    return result
