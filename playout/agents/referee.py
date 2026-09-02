"""LLM referee: both interact attempts in, structured verdict out, then deterministic apply."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic_ai import Agent

from playout.agents.model import llm_mode, openrouter_model, strong_model_name
from playout.canon import World
from playout.llm import LLM
from playout.models import (
    Action,
    AttackAction,
    DropAction,
    ExamineAction,
    InteractAction,
    KillAction,
    MoveAction,
    ObjectMutation,
    PerceptionOut,
    RefereeVerdict,
    SpeakAction,
    TakeAction,
    WaitAction,
    WriteNoteAction,
)
from playout.referee import apply_action
from playout.zh import with_prose

ALLOWED_KINDS = {
    "speak",
    "attack",
    "kill",
    "attempted_kill",
    "take",
    "drop",
    "examine",
    "write_note",
    "wait",
    "failed_speak",
    "failed_attack",
    "failed_take",
    "interact",
    "move",
}

REFEREE_SYSTEM = with_prose("""你是封閉正史模擬的裁判，不是人物。
兩造（或一造）用自然語言描述他們此刻試圖做的事。你根據場面、身體、物件、關係與體質，判定實際發生了什麼。

只回傳 JSON，欄位：
- summary: 一句已發生之事，繁體中文，寫進事件帶
- kind: speak / attack / kill / attempted_kill / take / drop / examine / write_note / wait / move / failed_speak / failed_attack / failed_take / interact
- patches: 可選，僅用這些 op：injure_actor, kill_actor, move_actor, reveal_object, rumor, add_object, destroy_object, describe_location
- speeches: [{speaker_id, hearer_id, text}] 實際說出的話（不是試圖說而沒說成的）
- perceptions: [{actor_id, text}] 每人真正見到、聽到的。不可把秘密塞給不知情的人
- objects: [{op: take|drop|reveal|write_note, object_id, actor_id, text}]
- relations: [{from_id, to_id, trust, resentment, note}] 可選

規則：
- 不可改寫已發生的事件。
- 不可殺死、打傷不在此地之人。
- 不可取走仍隱藏、且本回合尚未被察看揭開之物。
- 不可取走不在此地或已在別人手上之物。
- 移動只可到相鄰地點。
- 暴力可以失敗。無趁手的兵器、對方未受傷時，欲殺多半只成受傷（attempted_kill）。
- 若乙方不理（b_text 為空），仍要判定甲方單獨做成了什麼。
- 對白、summary、perceptions、detail 一律繁體中文。
""")


def named_present_actor(world: World, actor_id: str, text: str) -> str | None:
    actor = world.actor(actor_id)
    others = [
        x
        for x in world.actors_at(actor["location_id"])
        if x["id"] != actor_id and x["alive"]
    ]
    others.sort(key=lambda x: len(x["name"]), reverse=True)
    for o in others:
        if o["name"] in text or o["id"] in text or o["id"] in text.lower():
            return o["id"]
    markers = ("道", "說", "問", "「", "襲擊", "殺", "還手", "動手")
    if len(others) == 1 and any(m in text for m in markers):
        return others[0]["id"]
    return None


def named_object(world: World, actor_id: str, text: str, *, held: bool = False) -> str | None:
    actor = world.actor(actor_id)
    rows: list[Any] = []
    if held:
        rows.extend(world.inventory(actor_id))
    else:
        rows.extend(world.visible_objects(actor["location_id"]))
        rows.extend(world.inventory(actor_id))
    rows.sort(key=lambda o: len(o["name"]), reverse=True)
    low = text.lower()
    for obj in rows:
        if obj["id"] in text or obj["id"] in low or obj["name"] in text:
            return obj["id"]
        paren = f"（{obj['id']}）"
        if paren in text or f"({obj['id']})" in text:
            return obj["id"]
    return None


def extract_speech(text: str) -> str:
    for sep in ("道：", "道:", "說：", "說:", "：「"):
        if sep in text:
            return text.split(sep, 1)[1].strip("「」\"' ").strip()
    m = re.search(r"[「\"'](.+)[」\"']", text)
    if m:
        return m.group(1).strip()
    return text.strip()


def heuristic_action(world: World, actor_id: str, text: str) -> Action:
    raw = (text or "").strip()
    if not raw:
        return WaitAction()
    low = raw.lower()
    loc = world.actor(actor_id)["location_id"]
    target_id = named_present_actor(world, actor_id, raw)

    if any(w in raw for w in ("殺死", "要殺", "殺了")) or "kill" in low:
        if target_id:
            return KillAction(target=target_id)

    if any(w in raw for w in ("襲擊", "動手", "還手")) or "attack" in low:
        if target_id:
            return AttackAction(target=target_id)

    if any(w in raw for w in ("放下", "丟掉", "丟下")):
        oid = named_object(world, actor_id, raw, held=True)
        if oid:
            return DropAction(object_id=oid)

    if any(w in raw for w in ("取走", "拿起", "撿起")) or (
        "取" in raw and named_object(world, actor_id, raw)
    ):
        oid = named_object(world, actor_id, raw)
        if oid:
            return TakeAction(object_id=oid)

    if any(w in raw for w in ("察看", "細看", "搜看", "看看")):
        oid = named_object(world, actor_id, raw)
        return ExamineAction(target=oid or loc)

    if "寫" in raw and any(w in raw for w in ("紙", "信", "字")):
        return WriteNoteAction(text=raw[:200])

    dest = None
    for row in world.cx.execute("SELECT id, name FROM locations"):
        if row["id"] in raw or row["id"] in low or row["name"] in raw:
            dest = row["id"]
            break
    if dest and any(w in raw for w in ("前往", "走開", "離開", "過去", "走。", "走，")):
        return MoveAction(to=dest)
    if dest and ("往" in raw or "去" in raw) and dest != loc:
        return MoveAction(to=dest)

    if target_id:
        return SpeakAction(target=target_id, speech=extract_speech(raw)[:800])

    return WaitAction()


def action_as_interact_text(world: World, actor_id: str, action: Action) -> str | None:
    if isinstance(action, InteractAction):
        return action.text
    if isinstance(action, SpeakAction):
        try:
            name = world.actor(action.target)["name"]
        except Exception:
            name = action.target
        return f"對{name}道：{action.speech}"
    if isinstance(action, AttackAction):
        try:
            name = world.actor(action.target)["name"]
        except Exception:
            name = action.target
        return f"襲擊{name}"
    if isinstance(action, KillAction):
        try:
            name = world.actor(action.target)["name"]
        except Exception:
            name = action.target
        return f"要殺{name}"
    if isinstance(action, TakeAction):
        obj = world.object(action.object_id)
        label = obj["name"] if obj else action.object_id
        return f"取走{label}（{action.object_id}）"
    if isinstance(action, DropAction):
        obj = world.object(action.object_id)
        label = obj["name"] if obj else action.object_id
        return f"放下{label}（{action.object_id}）"
    if isinstance(action, ExamineAction):
        return f"察看{action.target}"
    if isinstance(action, WriteNoteAction):
        return f"寫下一紙：{action.text}"
    if isinstance(action, MoveAction):
        return f"前往{action.to}"
    return None


def scene_brief(world: World, a_id: str, b_id: str | None) -> str:
    a = world.actor(a_id)
    loc = world.location(a["location_id"])
    bodies = []
    for person in world.actors_at(a["location_id"], alive_only=False):
        inv = [
            {"id": o["id"], "name": o["name"]}
            for o in world.inventory(person["id"])
        ]
        bodies.append(
            {
                "id": person["id"],
                "name": person["name"],
                "alive": bool(person["alive"]),
                "injured": bool(person["injured"]),
                "constitution": person["constitution"],
                "inventory": inv,
            }
        )
    visible = [
        {
            "id": o["id"],
            "name": o["name"],
            "description": o["description"],
            "hidden": False,
        }
        for o in world.visible_objects(a["location_id"])
    ]
    hidden = [
        {"id": o["id"], "name": o["name"], "hidden": True}
        for o in world.visible_objects(a["location_id"], include_hidden=True)
        if o["hidden"]
    ]
    rels = []
    ids = [a_id] + ([b_id] if b_id else [])
    for src in ids:
        for dst in ids:
            if src == dst:
                continue
            row = world.relationship(src, dst)
            if row:
                rels.append(
                    {
                        "from": src,
                        "to": dst,
                        "trust": row["trust"],
                        "resentment": row["resentment"],
                        "notes": row["notes"],
                    }
                )
    adj = world.adjacent(a["location_id"])
    return json.dumps(
        {
            "location": {
                "id": loc["id"],
                "name": loc["name"],
                "description": loc["description"],
                "intact": bool(loc["intact"]),
                "adjacent": adj,
            },
            "bodies": bodies,
            "visible_objects": visible,
            "hidden_objects": hidden,
            "relationships": rels,
        },
        ensure_ascii=False,
    )


def apply_verdict(
    world: World,
    *,
    actor_id: str,
    counterpart_id: str | None,
    a_text: str,
    b_text: str | None,
    verdict: RefereeVerdict,
) -> dict[str, Any]:
    initiator = world.actor(actor_id)
    loc = initiator["location_id"]
    here = {p["id"] for p in world.actors_at(loc)}
    kind = verdict.kind if verdict.kind in ALLOWED_KINDS else "interact"

    eid = world.append_event(
        kind,
        (verdict.summary or "場上有事發生。")[:800],
        actor_id=actor_id,
        target_id=counterpart_id,
        payload={"a_text": a_text, "b_text": b_text},
    )

    from playout.storyteller import _apply_patch

    for patch in verdict.patches:
        op = patch.op
        if op == "kill_actor":
            if not patch.actor_id or patch.actor_id not in here:
                continue
            target = world.actor(patch.actor_id)
            if not target["alive"]:
                continue
            world.set_alive(patch.actor_id, False)
            world.perceive(
                eid,
                actor_id,
                patch.detail or f"你殺死了{target['name']}。",
            )
            for wid in here - {actor_id, patch.actor_id}:
                world.perceive(
                    eid, wid, patch.detail or f"{initiator['name']}殺死了{target['name']}。"
                )
            continue
        if op == "injure_actor":
            if not patch.actor_id or patch.actor_id not in here:
                continue
            target = world.actor(patch.actor_id)
            world.set_injured(patch.actor_id, True)
            world.perceive(eid, patch.actor_id, patch.detail or "你受傷了。")
            continue
        if op == "move_actor" and patch.actor_id and patch.location_id:
            mover = world.actor(patch.actor_id)
            if not mover["alive"]:
                continue
            if patch.location_id not in world.adjacent(mover["location_id"]):
                continue
            world.set_actor_location(patch.actor_id, patch.location_id)
            dest = world.location(patch.location_id)
            world.perceive(
                eid, patch.actor_id, patch.detail or f"你到了{dest['name']}。"
            )
            continue
        if op == "destroy_location":
            continue
        _apply_patch(world, eid, patch)

    revealed: set[str] = set()
    for mut in verdict.objects:
        if mut.op == "reveal" and mut.object_id:
            obj = world.object(mut.object_id)
            if not obj or obj["destroyed"]:
                continue
            if obj["location_id"] != loc:
                continue
            world.cx.execute(
                "UPDATE objects SET hidden=0 WHERE id=?", (mut.object_id,)
            )
            revealed.add(mut.object_id)
            world.perceive(eid, mut.actor_id or actor_id, mut.text or f"你看見{obj['name']}。")

    for mut in verdict.objects:
        if mut.op == "take" and mut.object_id:
            holder = mut.actor_id or actor_id
            obj = world.object(mut.object_id)
            if not obj or obj["destroyed"] or obj["holder_id"]:
                continue
            if obj["hidden"] and mut.object_id not in revealed:
                continue
            if obj["location_id"] != world.actor(holder)["location_id"]:
                continue
            world.cx.execute(
                "UPDATE objects SET holder_id=?, location_id=NULL WHERE id=?",
                (holder, mut.object_id),
            )
            world.perceive(eid, holder, mut.text or f"你取走{obj['name']}。")
        elif mut.op == "drop" and mut.object_id:
            holder = mut.actor_id or actor_id
            obj = world.object(mut.object_id)
            if not obj or obj["holder_id"] != holder:
                continue
            here_id = world.actor(holder)["location_id"]
            world.cx.execute(
                "UPDATE objects SET holder_id=NULL, location_id=? WHERE id=?",
                (here_id, mut.object_id),
            )
            world.perceive(eid, holder, mut.text or f"你放下{obj['name']}。")
        elif mut.op == "write_note":
            writer = mut.actor_id or actor_id
            apply_action(
                world, writer, WriteNoteAction(text=(mut.text or a_text)[:500])
            )

    for sp in verdict.speeches:
        try:
            speaker = world.actor(sp.speaker_id)
        except Exception:
            continue
        if speaker["location_id"] != loc:
            continue
        hearer = sp.hearer_id
        line = sp.text.strip()[:800]
        if not line:
            continue
        if hearer:
            try:
                other = world.actor(hearer)
            except Exception:
                other = None
            if other and other["location_id"] == loc:
                world.perceive(eid, sp.speaker_id, f"你對{other['name']}道：「{line}」")
                world.perceive(eid, hearer, f"{speaker['name']}對你道：「{line}」")
                continue
        world.perceive(eid, sp.speaker_id, f"你道：「{line}」")

    seen: set[tuple[str, str]] = set()
    for perc in verdict.perceptions:
        try:
            world.actor(perc.actor_id)
        except Exception:
            continue
        text = (perc.text or "").strip()[:800]
        if not text:
            continue
        key = (perc.actor_id, text)
        if key in seen:
            continue
        seen.add(key)
        world.perceive(eid, perc.actor_id, text)

    for rel in verdict.relations:
        try:
            world.actor(rel.from_id)
            world.actor(rel.to_id)
        except Exception:
            continue
        world.bump_relationship(
            rel.from_id,
            rel.to_id,
            trust=rel.trust,
            resentment=rel.resentment,
            note=rel.note or None,
        )

    if kind in ("attack", "kill", "attempted_kill") and counterpart_id:
        if kind == "kill":
            world.bump_relationship(
                actor_id, counterpart_id, resentment=3, note="殺了對方"
            )
        elif kind == "attempted_kill":
            world.bump_relationship(
                counterpart_id, actor_id, trust=-5, resentment=5, note="要殺我"
            )
        else:
            world.bump_relationship(
                counterpart_id, actor_id, trust=-3, resentment=3, note="襲擊了我"
            )

    world.cx.commit()
    return {
        "ok": True,
        "event_id": eid,
        "summary": verdict.summary,
        "kind": kind,
        "action": {"type": "interact", "text": a_text},
    }


class RefereeAgent:
    def __init__(self, llm: LLM | None = None):
        self.llm = llm or LLM()

    async def judge(
        self,
        world: World,
        *,
        a_id: str,
        a_text: str,
        b_id: str | None,
        b_text: str | None,
    ) -> dict[str, Any]:
        if self.llm.mode == "mock" or llm_mode() == "mock":
            return self._mock_judge(
                world, a_id=a_id, a_text=a_text, b_id=b_id, b_text=b_text
            )
        try:
            return await self._live_judge(
                world, a_id=a_id, a_text=a_text, b_id=b_id, b_text=b_text
            )
        except Exception:
            return self._mock_judge(
                world, a_id=a_id, a_text=a_text, b_id=b_id, b_text=b_text
            )

    def _mock_judge(
        self,
        world: World,
        *,
        a_id: str,
        a_text: str,
        b_id: str | None,
        b_text: str | None,
    ) -> dict[str, Any]:
        a_action = heuristic_action(world, a_id, a_text)
        r1 = apply_action(world, a_id, a_action)
        r1["action"] = a_action.model_dump()
        r2: dict[str, Any] | None = None
        if b_id:
            if b_text and b_text.strip():
                b_action = heuristic_action(world, b_id, b_text)
            else:
                b_action = WaitAction()
            r2 = apply_action(world, b_id, b_action)
            r2["action"] = b_action.model_dump()
        first_eid = r1.get("event_id") or (r2 or {}).get("event_id")
        ev = None
        if first_eid:
            ev = world.cx.execute(
                "SELECT summary, kind FROM events WHERE id=?", (first_eid,)
            ).fetchone()
        return {
            "ok": bool(r1.get("ok", True)),
            "event_id": first_eid,
            "summary": (ev["summary"] if ev else "") or r1.get("reason", ""),
            "kind": (ev["kind"] if ev else "interact"),
            "action": {"type": "interact", "text": a_text},
            "a_result": r1,
            "b_result": r2,
        }

    async def _live_judge(
        self,
        world: World,
        *,
        a_id: str,
        a_text: str,
        b_id: str | None,
        b_text: str | None,
    ) -> dict[str, Any]:
        a = world.actor(a_id)
        b = world.actor(b_id) if b_id else None
        user = (
            f"場面：{scene_brief(world, a_id, b_id)}\n"
            f"甲方 {a['name']}（{a_id}）試圖：{a_text}\n"
            f"乙方 "
            + (
                f"{b['name']}（{b_id}）試圖：{b_text}"
                if b is not None and b_text
                else (
                    f"{b['name']}（{b_id}）不理。"
                    if b is not None
                    else "無人對持；這是單獨行事。"
                )
            )
        )
        agent: Agent[None, RefereeVerdict] = Agent(
            openrouter_model(strong_model_name()),
            output_type=RefereeVerdict,
            instructions=REFEREE_SYSTEM,
        )
        out = await agent.run(user)
        verdict = out.output
        if not isinstance(verdict, RefereeVerdict):
            verdict = RefereeVerdict(summary=a_text, kind="interact")
        if not verdict.summary:
            verdict.summary = a_text[:200]
        return apply_verdict(
            world,
            actor_id=a_id,
            counterpart_id=b_id,
            a_text=a_text,
            b_text=b_text,
            verdict=verdict,
        )
