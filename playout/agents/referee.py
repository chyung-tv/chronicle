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
    "failed_move",
    "forced_move",
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
- 移動只可到相鄰且完好的地點。不可寫未走到之地。
- 實際說出的話必須放進 speeches，原文加引號，不可只寫「打了招呼」。
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


def peel_speech_quotes(text: str) -> str:
    """Strip wrapping quotes so we do not emit 「「line」」 in the tape."""
    s = (text or "").strip()
    pairs = (("「", "」"), ("『", "』"), ("“", "”"), ('"', '"'), ("'", "'"))
    changed = True
    while s and changed:
        changed = False
        for a, b in pairs:
            if len(s) >= 2 and s.startswith(a) and s.endswith(b):
                s = s[len(a) : len(s) - len(b)].strip()
                changed = True
                break
    return s


def extract_speech(text: str) -> str:
    for sep in ("道：", "道:", "說：", "說:", "：「"):
        if sep in text:
            return peel_speech_quotes(text.split(sep, 1)[1])
    m = re.search(r"[「\"'](.+)[」\"']", text)
    if m:
        return peel_speech_quotes(m.group(1))
    return peel_speech_quotes(text)


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
    node = world.node(a["location_id"])
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
            "id": o.id,
            "name": o.name,
            "description": o.description,
            "hidden": False,
        }
        for o in node.visible_objects
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
    return json.dumps(
        {
            "location": {
                "id": node.id,
                "name": node.name,
                "description": node.description,
                "intact": node.intact,
                "connected": [e.model_dump() for e in node.connected],
                "exits": [e.id for e in world.exits(node.id)],
            },
            "bodies": bodies,
            "visible_objects": visible,
            "hidden_objects": hidden,
            "relationships": rels,
        },
        ensure_ascii=False,
    )


def _summary_claims_failed_hop(summary: str, failed: list) -> bool:
    blob = summary or ""
    for res in failed:
        if res.to_id and res.to_id in blob:
            return True
        if res.dest_name and res.dest_name in blob:
            return True
    if not failed:
        return False
    walk = ("前往", "走向", "走到", "去了")
    return any(w in blob for w in walk)


def apply_verdict(
    world: World,
    *,
    actor_id: str,
    counterpart_id: str | None,
    a_text: str,
    b_text: str | None,
    verdict: RefereeVerdict,
) -> dict[str, Any]:
    from playout.models import MoveIntent
    from playout.movement import apply_move, write_move_perceptions
    from playout.storyteller import _apply_patch

    initiator = world.actor(actor_id)
    start_loc = initiator["location_id"]
    here = {p["id"] for p in world.actors_at(start_loc)}
    kind = verdict.kind if verdict.kind in ALLOWED_KINDS else "interact"
    pending: list[tuple[str, str]] = []
    ok_moves: list = []
    failed_moves: list = []

    for patch in verdict.patches:
        op = patch.op
        if op == "kill_actor":
            if not patch.actor_id or patch.actor_id not in here:
                continue
            target = world.actor(patch.actor_id)
            if not target["alive"]:
                continue
            world.set_alive(patch.actor_id, False)
            pending.append(
                (actor_id, patch.detail or f"你殺死了{target['name']}。")
            )
            for wid in here - {actor_id, patch.actor_id}:
                pending.append(
                    (
                        wid,
                        patch.detail or f"{initiator['name']}殺死了{target['name']}。",
                    )
                )
            continue
        if op == "injure_actor":
            if not patch.actor_id or patch.actor_id not in here:
                continue
            target = world.actor(patch.actor_id)
            world.set_injured(patch.actor_id, True)
            pending.append((patch.actor_id, patch.detail or "你受傷了。"))
            continue
        if op == "move_actor" and patch.actor_id and patch.location_id:
            res = apply_move(
                world,
                MoveIntent(
                    actor_id=patch.actor_id,
                    to=patch.location_id,
                    kind="voluntary",
                ),
                record_event=False,
                detail=patch.detail or None,
            )
            if res.ok:
                ok_moves.append(res)
            else:
                failed_moves.append(res)
            continue
        if op == "destroy_location":
            continue
        # Other patches (objects, rumor, weather…) need an event id; apply after seal.

    revealed: set[str] = set()
    object_notes: list[tuple[str, str]] = []
    for mut in verdict.objects:
        if mut.op == "reveal" and mut.object_id:
            obj = world.object(mut.object_id)
            if not obj or obj["destroyed"]:
                continue
            if obj["location_id"] != start_loc:
                continue
            world.cx.execute(
                "UPDATE objects SET hidden=0 WHERE id=?", (mut.object_id,)
            )
            revealed.add(mut.object_id)
            object_notes.append(
                (mut.actor_id or actor_id, mut.text or f"你看見{obj['name']}。")
            )

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
            object_notes.append((holder, mut.text or f"你取走{obj['name']}。"))
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
            object_notes.append((holder, mut.text or f"你放下{obj['name']}。"))

    accepted_speeches: list[dict[str, str | None]] = []
    speech_notes: list[tuple[str, str]] = []
    for sp in verdict.speeches:
        try:
            speaker = world.actor(sp.speaker_id)
        except Exception:
            continue
        line = peel_speech_quotes((sp.text or "").strip()[:800])
        if not line:
            continue
        hearer = sp.hearer_id
        if hearer:
            try:
                other = world.actor(hearer)
            except Exception:
                other = None
            if (
                other
                and other["location_id"] == speaker["location_id"]
            ):
                speech_notes.append(
                    (sp.speaker_id, f"你對{other['name']}道：「{line}」")
                )
                speech_notes.append(
                    (hearer, f"{speaker['name']}對你道：「{line}」")
                )
                for wid in world.actors_at(speaker["location_id"]):
                    if wid["id"] in {sp.speaker_id, hearer}:
                        continue
                    speech_notes.append(
                        (
                            wid["id"],
                            f"{speaker['name']}對{other['name']}道：「{line}」",
                        )
                    )
                accepted_speeches.append(
                    {
                        "speaker_id": sp.speaker_id,
                        "hearer_id": hearer,
                        "text": line,
                    }
                )
                continue
        # Unaddressed line: only if speaker is still at the event node or just arrived.
        if speaker["location_id"] != start_loc and sp.speaker_id not in {
            r.actor_id for r in ok_moves
        }:
            continue
        speech_notes.append((sp.speaker_id, f"你道：「{line}」"))
        accepted_speeches.append(
            {"speaker_id": sp.speaker_id, "hearer_id": None, "text": line}
        )

    summary = (verdict.summary or "場上有事發生。")[:800]
    if failed_moves and not ok_moves:
        if kind == "move" or _summary_claims_failed_hop(summary, failed_moves):
            kind = "failed_move"
            summary = failed_moves[0].summary
    elif ok_moves and kind == "move":
        if _summary_claims_failed_hop(summary, failed_moves):
            summary = ok_moves[0].summary
    if accepted_speeches and kind in ("interact", "speak"):
        kind = "speak"
        if "「" not in summary:
            first = accepted_speeches[0]
            speaker = world.actor(str(first["speaker_id"]))
            hearer_id = first.get("hearer_id")
            line = str(first["text"])
            if hearer_id:
                hearer = world.actor(str(hearer_id))
                summary = f"{speaker['name']}對{hearer['name']}道：「{line}」"
            else:
                summary = f"{speaker['name']}道：「{line}」"

    mover_ids = {r.actor_id for r in ok_moves}
    dest_ids = {r.to_id for r in ok_moves if r.to_id}
    payload: dict[str, Any] = {
        "a_text": a_text,
        "b_text": b_text,
        "speeches": accepted_speeches,
        "location_id": start_loc,
    }
    if ok_moves:
        payload["from"] = ok_moves[0].from_id
        payload["to"] = ok_moves[0].to_id
    elif failed_moves:
        payload["from"] = failed_moves[0].from_id
        payload["to"] = failed_moves[0].to_id
        payload["reason"] = failed_moves[0].reason

    eid = world.append_event(
        kind,
        summary,
        actor_id=actor_id,
        target_id=counterpart_id,
        payload=payload,
    )

    for res in ok_moves + failed_moves:
        write_move_perceptions(world, eid, res)

    for aid, text in pending + object_notes + speech_notes:
        world.perceive(eid, aid, text)

    allowed_perc: set[str] = set()
    for p in world.actors_at(start_loc):
        allowed_perc.add(p["id"])
    allowed_perc.update(mover_ids)
    for dest in dest_ids:
        for p in world.actors_at(dest):
            allowed_perc.add(p["id"])

    seen: set[tuple[str, str]] = set()
    for perc in verdict.perceptions:
        try:
            person = world.actor(perc.actor_id)
        except Exception:
            continue
        if perc.actor_id not in allowed_perc:
            continue
        if person["location_id"] not in {start_loc, *dest_ids} and perc.actor_id not in mover_ids:
            continue
        text = (perc.text or "").strip()[:800]
        if not text:
            continue
        # Drop free-form claims of a hop that did not happen.
        skip = False
        for res in failed_moves:
            if res.dest_name and res.dest_name in text and perc.actor_id == res.actor_id:
                skip = True
                break
        if skip:
            continue
        key = (perc.actor_id, text)
        if key in seen:
            continue
        seen.add(key)
        world.perceive(eid, perc.actor_id, text)

    for patch in verdict.patches:
        if patch.op in (
            "kill_actor",
            "injure_actor",
            "move_actor",
            "destroy_location",
        ):
            continue
        _apply_patch(world, eid, patch)

    for mut in verdict.objects:
        if mut.op == "write_note":
            writer = mut.actor_id or actor_id
            apply_action(
                world, writer, WriteNoteAction(text=(mut.text or a_text)[:500])
            )

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
        "summary": summary,
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
