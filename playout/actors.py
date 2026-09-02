"""Actor turns: private context only. Goals update from perception, never from steer."""

from __future__ import annotations

from playout.canon import World
from playout.llm import LLM
from playout.models import ActorDecision, InteractAction, WaitAction, action_from_dict
from playout.zh import with_prose

ACTOR_SYSTEM = with_prose("""你是活在故事裡的人物，須守住人格，不是助手。
你只知道自己感知過、寫進日記的事。別人的秘密，除非你已得知，否則你不知道。
目標由你自己從所見所聞長出。誰也不能替你派一個目標。

只回傳 JSON：
{"thought": "私心，繁體中文", "goal_update": null 或一句新目標, "mood": "一字心境", "action": { ... }}

Action must be one of:
{"type":"move","to":"<location_id>"}
{"type":"interact","text":"你此刻試圖做的事，自然語言，繁體中文"}
{"type":"wait"}

規則：
- interact 可對在場之人說話、取物、察看、動手、寫紙。點出對方姓名或 id。
- move 只能去相鄰的 location_id。
- 不要敘述世界。只選一個行動。
- 若你自己決定，可以動武。勿輕易殺人。
thought、goal_update、interact 的 text 一律繁體中文。
""")


def private_context(world: World, actor_id: str, extra: str = "") -> str:
    from playout.agents.views import view_as_prompt

    return view_as_prompt(world, actor_id, extra)


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
        attacker_name = others[0]["name"] if others else ""
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
                    attacker_name = name
        if attacker:
            return ActorDecision(
                thought="不能不還手。",
                action=InteractAction(text=f"襲擊{attacker_name}"),
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
            action=InteractAction(text=f"對{t['name']}道：{speech}"),
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
            action=InteractAction(text=f"察看此地（{loc}）"),
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
                    action=InteractAction(text=f"察看{obj['name']}（{obj['id']}）"),
                )
            return ActorDecision(
                thought="或許用得著。",
                action=InteractAction(text=f"取走{obj['name']}（{obj['id']}）"),
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
            action=InteractAction(text=f"對{t['name']}道：{speech}"),
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
    from playout.agents.actor import ActorAgent

    return ActorAgent(llm).run(world, actor_id, extra=extra)
