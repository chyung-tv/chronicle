"""Steer: future-facing intents become campaigns. Never retcon. Never puppet the climax."""

from __future__ import annotations

import json
import re
from typing import Any

from playout.canon import World
from playout.llm import LLM
from playout.models import Patch, SteerCampaign, SteerRung, StorytellerPlan
from playout.storyteller import apply_patches
from playout.zh import with_prose

STEER_SYSTEM = with_prose("""你是封閉正史模擬的戲場總管。
人點出一個希望「變得可能」的未來，例如「林樂安應當殺了高亦禮」。
你發明一場全新刺激的戰役（動機、手段、時機、加壓）。
你不可：
- 改寫任何人的記憶或日記
- 派發目標（「林樂安決定殺人」）
- 代為完成高潮（不可 kill 補丁，不可強迫出手）
- 捏造假過去（除非人物設定裡本有未揭的種子）

你可以：
- 添物件、流言、環境牽引、揭開隱藏的設定物件
- 不可用傷害當捷徑
- 使用已有的願、秘密、舊怨

只回傳 JSON：
{
  "summary": "短句，繁體中文",
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
Steer 戰役禁用 kill_actor、injure_actor。
injection.summary 與 patch.detail 一律繁體中文。
""")


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


def _search_label(text: str, label: str):
    if not label:
        return None
    if re.search(r"[A-Za-z]", label):
        return re.search(rf"\b{re.escape(label)}\b", text, re.I)
    return re.search(re.escape(label), text)


def _parse_pair(text: str, actors: list[dict]) -> tuple[str | None, str | None]:
    hits: list[tuple[int, str]] = []
    for a in actors:
        labels = {a["id"], a["name"]}
        if " " in a["name"]:
            labels.add(a["name"].split()[0])
        for label in labels:
            m = _search_label(text, label)
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
                    detail="碼頭上有孩子說，關宅門未閂，桌上攤著紙。",
                )
            )
        motive_patches.extend([
            Patch(
                op="reveal_object",
                object_id="affair_letter",
                detail=f"桌上有關瑪手跡，點了{b['name']}的名。",
            ),
            Patch(
                op="rumor",
                actor_ids=[a_id],
                detail=f"你讀到一封信，點了{b['name']}的名。這是此刻桌上的紙，不是你素來記得的往事。",
            ),
        ])
    else:
        motive_patches = [
            Patch(
                op="add_object",
                object_id=f"steer_proof_{a_id}_{b_id}",
                name="撕下的帳頁",
                location_id=a["location_id"],
                detail=f"{b['name']}的字跡，寫明如何奪{a['name']}所愛。",
            ),
            Patch(
                op="rumor",
                actor_ids=[a_id],
                detail=f"你得著憑據：{b['name']}正在算計你。不是記憶——是紙，此刻若伸手便可取。",
            ),
        ]
    means = [
        Patch(
            op="add_object",
            object_id=f"steer_means_{a_id}",
            name="魚刀",
            location_id=a["location_id"],
            detail="一把新磨的長魚刀。無人看管。",
        ),
        Patch(
            op="rumor",
            actor_ids=[a_id],
            detail="刀就在你夠得到的地方。你不必拿。它只是在。",
        ),
    ]
    # isolate: park others elsewhere, put A and B together
    isolate_loc = b["location_id"]
    opp: list[Patch] = [
        Patch(
            op="move_actor",
            actor_id=a_id,
            location_id=isolate_loc,
            detail=f"你聽說{b['name']}獨自在。風聲掩過別的聲音。",
        )
    ]
    for other in world.living_actors():
        if other["id"] in (a_id, b_id):
            continue
        if other["location_id"] == isolate_loc:
            refuge = next(
                (x for x in world.adjacent(isolate_loc) if x), other["location_id"]
            )
            opp.append(
                Patch(
                    op="move_actor",
                    actor_id=other["id"],
                    location_id=refuge,
                    detail="別處有人喊，把你扯走。",
                )
            )
    esc = [
        Patch(
            op="rumor",
            actor_ids=[a_id],
            detail=f"風聲傳來：{b['name']}要在颱風前對你下手。再等，也是一種死。",
        ),
        Patch(
            op="rumor",
            actor_ids=[b_id],
            detail=f"你聽說{a['name']}在找你。神色不對。看好門。",
        ),
    ]
    return SteerCampaign(
        summary=f"令{a['name']}有機會傷害{b['name']}，卻不代他們下手。",
        success_predicates=[f"kill:{a_id}->{b_id}"],
        failure_predicates=[f"dead:{a_id}", f"kill:{b_id}->{a_id}"],
        rungs=[
            SteerRung(
                id="motive",
                kind="motive",
                injection=StorytellerPlan(
                    summary=f"動機落到{a['name']}身上。", patches=motive_patches
                ),
            ),
            SteerRung(
                id="means",
                kind="means",
                injection=StorytellerPlan(
                    summary=f"{a['name']}手邊出現兵器。", patches=means
                ),
            ),
            SteerRung(
                id="opportunity",
                kind="opportunity",
                injection=StorytellerPlan(
                    summary=f"{a['name']}與{b['name']}或將獨處。", patches=opp
                ),
            ),
            SteerRung(
                id="escalation",
                kind="escalation",
                injection=StorytellerPlan(summary="壓力上來了。", patches=esc),
            ),
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
                    if (
                        e["kind"] in ("kill",)
                        and e["actor_id"] == src
                        and e["target_id"] == dst
                    ):
                        return True
        elif p.startswith("attempt:"):
            rest = p.split(":", 1)[1]
            src, dst = rest.split("->", 1)
            for e in events:
                if (
                    e["kind"] == "attempted_kill"
                    and e["actor_id"] == src
                    and e["target_id"] == dst
                ):
                    return True
        elif p.startswith("injured:"):
            aid = p.split(":", 1)[1]
            row = world.actor(aid)
            if row["injured"]:
                return True
    return False


def _forbidden_ops(campaign: SteerCampaign) -> SteerCampaign:
    allowed = {
        "rumor",
        "broadcast",
        "add_object",
        "reveal_object",
        "move_actor",
        "describe_location",
        "set_weather",
    }
    for rung in campaign.rungs:
        rung.injection.patches = [p for p in rung.injection.patches if p.op in allowed]
    return campaign


def submit_intent(world: World, llm: LLM, text: str) -> dict[str, Any]:
    actors = _index_actors(world)
    locs = [
        {"id": l["id"], "name": l["name"]}
        for l in world.cx.execute("SELECT id,name FROM locations")
    ]
    hidden = [
        {"id": o["id"], "name": o["name"], "location": o["location_id"]}
        for o in world.cx.execute(
            "SELECT * FROM objects WHERE hidden=1 AND destroyed=0"
        )
    ]
    user = (
        f"意圖：{text}\n第{world.day}日 {world.time_label}\n"
        f"人物：{json.dumps(actors, ensure_ascii=False)}\n"
        f"地點：{json.dumps(locs, ensure_ascii=False)}\n"
        f"未揭之物：{json.dumps(hidden, ensure_ascii=False)}"
    )
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
    return {
        "id": int(cur.lastrowid),
        "status": "brewing",
        "campaign": campaign.model_dump(),
    }


def _save_campaign(
    world: World, intent_id: int, status: str, campaign: SteerCampaign
) -> None:
    world.cx.execute(
        "UPDATE steer_intents SET status=?, campaign=? WHERE id=?",
        (status, campaign.model_dump_json(), intent_id),
    )
    world.cx.commit()


def harvest_injections(world: World) -> list[dict[str, Any]]:
    """Resolve succeeded/failed. Return next pending rung per intent without writing World."""
    out: list[dict[str, Any]] = []
    rows = list(
        world.cx.execute(
            "SELECT * FROM steer_intents WHERE status IN ('brewing','attempted')"
        )
    )
    for row in rows:
        campaign = SteerCampaign.model_validate(json.loads(row["campaign"]))
        if _eval_predicates(world, campaign.success_predicates):
            _save_campaign(world, row["id"], "succeeded", campaign)
            continue
        if _eval_predicates(world, campaign.failure_predicates):
            _save_campaign(world, row["id"], "failed", campaign)
            continue
        if _eval_predicates(
            world,
            [
                p.replace("kill:", "attempt:")
                for p in campaign.success_predicates
                if p.startswith("kill:")
            ],
        ):
            if row["status"] != "attempted":
                _save_campaign(world, row["id"], "attempted", campaign)
                row = {k: row[k] for k in row.keys()}
                row["status"] = "attempted"
        pending = next((r for r in campaign.rungs if r.status == "pending"), None)
        if pending:
            out.append(
                {
                    "intent_id": row["id"],
                    "rung_id": pending.id,
                    "kind": pending.kind,
                    "plan": pending.injection.model_dump(),
                    "status": row["status"],
                }
            )
    return out


def mark_rung_injected(world: World, intent_id: int, rung_id: str) -> None:
    row = world.cx.execute(
        "SELECT * FROM steer_intents WHERE id=?", (intent_id,)
    ).fetchone()
    if not row:
        return
    campaign = SteerCampaign.model_validate(json.loads(row["campaign"]))
    for rung in campaign.rungs:
        if rung.id == rung_id:
            rung.status = "injected"
            break
    status = "attempted" if row["status"] == "attempted" else "brewing"
    if _eval_predicates(world, campaign.success_predicates):
        status = "succeeded"
    elif _eval_predicates(world, campaign.failure_predicates):
        status = "failed"
    _save_campaign(world, intent_id, status, campaign)


def tick_intents(world: World) -> list[dict[str, Any]]:
    """After a scene: resolve or inject the next rung. One injection per intent per tick."""
    out = []
    rows = list(
        world.cx.execute(
            "SELECT * FROM steer_intents WHERE status IN ('brewing','attempted')"
        )
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
        if _eval_predicates(
            world,
            [
                p.replace("kill:", "attempt:")
                for p in campaign.success_predicates
                if p.startswith("kill:")
            ],
        ):
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
