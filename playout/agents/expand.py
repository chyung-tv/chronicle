"""LocationWriter and ActorWriter: propose spawn/edit patches. apply_patches commits."""

from __future__ import annotations

from typing import Any

from playout.canon import World
from playout.ids import is_vague_place, slugify
from playout.llm import LLM
from playout.models import (
    ACTOR_WRITER_OPS,
    LOCATION_WRITER_OPS,
    MAX_ACTORS,
    MAX_LOCATIONS,
    ActorSetup,
    LocationSetup,
    Patch,
    StorySetup,
    StorytellerPlan,
)
from playout.storyteller import apply_patches
from playout.zh import with_prose

LOCATION_WRITER_SYSTEM = with_prose("""你是封閉正史模擬的地點書記。人要走向或改寫一處地方。你決定那地方此刻是否存在、如何連上地圖、裡面有何物。

只回傳 JSON：{"summary":"一句繁體中文","patches":[...]}

可用 op：add_location, add_edge, describe_location, destroy_location, add_object, describe_object, destroy_object, reveal_object。

規則：
- 具體地名才可新增。含糊的「某處」「外面」不可新增。
- 新增地點必須 connect_to 當下所在之處，使它相鄰可走。
- 地點總數不可超過上限。已滿則 patches 為空，summary 寫找不到。
- 不可殺人、不可派目標、不可寫對白。
- 不改過去。
""")

ACTOR_WRITER_SYSTEM = with_prose("""你是封閉正史模擬的人物書記。人要找、改、傷、或殺死一個人物。你決定那人此刻是否在場、傷勢如何。

只回傳 JSON：{"summary":"一句繁體中文","patches":[...]}

可用 op：add_actor, edit_actor, injure_actor, kill_actor, rumor。

規則：
- 具體人名才可新增。含糊的「有人」不可新增。
- 人物不可刪，只可殺（kill_actor，alive=0）。
- 受傷用 injure_actor 或 edit_actor，condition 寫清何處受傷，如「左臂受傷」。
- 人物總數不可超過上限。已滿則 patches 為空。
- 不可改地點拓撲，不可派目標。
- 不改過去。
""")


def _perceptions_blob(world: World, actor_id: str) -> str:
    rows = world.perceptions_for(actor_id, limit=8)
    return "\n".join(p["text"] for p in rows) or "（無）"


def _place_context(world: World, origin_id: str, name: str, actor_id: str) -> str:
    origin = world.location(origin_id)
    locs = [{"id": r["id"], "name": r["name"]} for r in world.cx.execute("SELECT id,name FROM locations")]
    n = world.location_count()
    return (
        f"要去：{name}\n"
        f"此刻在：{origin['id']}（{origin['name']}）\n"
        f"既有地點：{locs}\n"
        f"地點數 {n}/{MAX_LOCATIONS}\n"
        f"近時感知：\n{_perceptions_blob(world, actor_id)}"
    )


def _actor_context(world: World, here_id: str, name: str, actor_id: str) -> str:
    people = [
        {"id": a["id"], "name": a["name"], "location": a["location_id"]}
        for a in world.cx.execute("SELECT id,name,location_id FROM actors")
    ]
    n = world.actor_count()
    return (
        f"要找：{name}\n"
        f"此地：{here_id}\n"
        f"既有人物：{people}\n"
        f"人數 {n}/{MAX_ACTORS}\n"
        f"近時感知：\n{_perceptions_blob(world, actor_id)}"
    )


def _heuristic_place_plan(
    world: World, origin_id: str, name: str
) -> StorytellerPlan | None:
    if is_vague_place(name) or world.find_location(name):
        return None
    if world.location_count() >= MAX_LOCATIONS:
        return None
    loc_id = slugify(name, "loc", world.used_location_ids())
    return StorytellerPlan(
        summary=f"{name}就在附近。",
        patches=[
            Patch(
                op="add_location",
                location_id=loc_id,
                name=name.strip(),
                detail=f"{name.strip()}。你剛走到這兒。",
                connect_to=origin_id,
            )
        ],
    )


def _heuristic_person_plan(
    world: World, here_id: str, name: str
) -> StorytellerPlan | None:
    if is_vague_place(name) or world.find_actor(name):
        return None
    if world.actor_count() >= MAX_ACTORS:
        return None
    if len((name or "").strip()) < 2:
        return None
    aid = slugify(name, "npc", world.used_actor_ids())
    return StorytellerPlan(
        summary=f"{name}在此地。",
        patches=[
            Patch(
                op="add_actor",
                actor_id=aid,
                name=name.strip(),
                location_id=here_id,
                voice=f"{name.strip()}的口吻尚未定。",
                want="尚未定願。",
                constitution="尚未定性。",
                detail=f"{name.strip()}就在你眼前。",
            )
        ],
    )


def _heuristic_object_plan(
    world: World, here_id: str, name: str
) -> StorytellerPlan | None:
    if is_vague_place(name) or world.find_object(name):
        return None
    oid = slugify(name, "obj", world.used_object_ids())
    return StorytellerPlan(
        summary=f"{name}在此地。",
        patches=[
            Patch(
                op="add_object",
                object_id=oid,
                name=name.strip(),
                location_id=here_id,
                detail=f"{name.strip()}。",
            )
        ],
    )


class LocationWriter:
    def __init__(self, llm: LLM | None = None):
        self.llm = llm or LLM()

    def plan_place(
        self, world: World, origin_id: str, name: str, actor_id: str
    ) -> StorytellerPlan | None:
        if is_vague_place(name) or world.find_location(name):
            return None
        if world.location_count() >= MAX_LOCATIONS:
            return None
        if self.llm.mode == "live":
            from playout.agents.model import llm_mode, openrouter_model, strong_model_name
            from pydantic_ai import Agent

            if llm_mode() == "live":
                agent: Agent[None, StorytellerPlan] = Agent(
                    openrouter_model(strong_model_name()),
                    output_type=StorytellerPlan,
                    instructions=LOCATION_WRITER_SYSTEM,
                )
                try:
                    out = agent.run_sync(_place_context(world, origin_id, name, actor_id))
                    plan = out.output
                    if isinstance(plan, StorytellerPlan) and plan.patches:
                        return plan
                except Exception:
                    pass
        return _heuristic_place_plan(world, origin_id, name)

    def materialize_place(
        self, world: World, origin_id: str, name: str, actor_id: str
    ) -> str | None:
        plan = self.plan_place(world, origin_id, name, actor_id)
        if not plan or not plan.patches:
            return None
        apply_patches(
            world, plan, kind="expand_location", allow=LOCATION_WRITER_OPS
        )
        found = world.find_location(name)
        if found:
            return found["id"]
        for p in plan.patches:
            if p.op == "add_location" and p.location_id:
                try:
                    return world.location(p.location_id)["id"]
                except Exception:
                    continue
        return None

    def insert(self, world: World, text: str) -> dict[str, Any]:
        hit = world.find_location(text)
        t = text.lower()
        destroy = any(
            w in t or w in text
            for w in ("destroy", "ruin", "collapse", "毀", "倒塌", "炸掉")
        )
        if destroy and hit:
            plan = StorytellerPlan(
                summary=text.strip(),
                patches=[
                    Patch(
                        op="destroy_location",
                        location_id=hit["id"],
                        detail=text.strip(),
                    )
                ],
            )
        elif hit:
            plan = StorytellerPlan(
                summary=text.strip(),
                patches=[
                    Patch(
                        op="describe_location",
                        location_id=hit["id"],
                        detail=text.strip(),
                    )
                ],
            )
        else:
            home = world.cx.execute(
                "SELECT id FROM locations ORDER BY id LIMIT 1"
            ).fetchone()
            origin = home["id"] if home else ""
            name = text.strip()[:40] or "新處"
            plan = _heuristic_place_plan(world, origin, name) or StorytellerPlan(
                summary="找不到可寫的地方。", patches=[]
            )
        if self.llm.mode == "live":
            from playout.agents.model import llm_mode, openrouter_model, strong_model_name
            from pydantic_ai import Agent

            if llm_mode() == "live":
                locs = [
                    {"id": r["id"], "name": r["name"]}
                    for r in world.cx.execute("SELECT id,name FROM locations")
                ]
                user = f"意圖：{text}\n地點：{locs}\n上限：{MAX_LOCATIONS}"
                agent: Agent[None, StorytellerPlan] = Agent(
                    openrouter_model(strong_model_name()),
                    output_type=StorytellerPlan,
                    instructions=LOCATION_WRITER_SYSTEM,
                )
                try:
                    out = agent.run_sync(user)
                    if isinstance(out.output, StorytellerPlan) and out.output.patches:
                        plan = out.output
                except Exception:
                    pass
        if not plan.patches:
            return {"ok": False, "summary": plan.summary, "patches": []}
        eid = apply_patches(
            world, plan, kind="god_location", allow=LOCATION_WRITER_OPS
        )
        world.set_meta("idle_scenes", "0")
        world.cx.commit()
        return {
            "ok": True,
            "event_id": eid,
            "summary": plan.summary,
            "patches": [p.model_dump() for p in plan.patches],
        }

    def draft(self, setup: StorySetup, extras: list[LocationSetup]) -> StorySetup:
        locs = list(setup.locations)
        used = {loc.id for loc in locs}
        edges = list(setup.edges)
        for loc in extras:
            if len(locs) >= MAX_LOCATIONS:
                break
            if loc.id in used:
                continue
            locs.append(loc)
            used.add(loc.id)
            if locs:
                parent = setup.locations[0].id
                edges.append((parent, loc.id))
        objects = list(setup.objects)
        return setup.model_copy(update={"locations": locs, "edges": edges, "objects": objects})


class ActorWriter:
    def __init__(self, llm: LLM | None = None):
        self.llm = llm or LLM()

    def plan_person(
        self, world: World, here_id: str, name: str, actor_id: str
    ) -> StorytellerPlan | None:
        if world.find_actor(name):
            return None
        if world.actor_count() >= MAX_ACTORS:
            return None
        if self.llm.mode == "live":
            from playout.agents.model import llm_mode, openrouter_model, strong_model_name
            from pydantic_ai import Agent

            if llm_mode() == "live":
                agent: Agent[None, StorytellerPlan] = Agent(
                    openrouter_model(strong_model_name()),
                    output_type=StorytellerPlan,
                    instructions=ACTOR_WRITER_SYSTEM,
                )
                try:
                    out = agent.run_sync(_actor_context(world, here_id, name, actor_id))
                    plan = out.output
                    if isinstance(plan, StorytellerPlan) and plan.patches:
                        return plan
                except Exception:
                    pass
        return _heuristic_person_plan(world, here_id, name)

    def materialize_person(
        self, world: World, here_id: str, name: str, actor_id: str
    ) -> str | None:
        plan = self.plan_person(world, here_id, name, actor_id)
        if not plan or not plan.patches:
            return None
        apply_patches(world, plan, kind="expand_actor", allow=ACTOR_WRITER_OPS)
        found = world.find_actor(name)
        if found:
            return found["id"]
        for p in plan.patches:
            if p.op == "add_actor" and p.actor_id:
                try:
                    return world.actor(p.actor_id)["id"]
                except Exception:
                    continue
        return None

    def materialize_object(
        self, world: World, here_id: str, name: str, actor_id: str
    ) -> str | None:
        if world.find_object(name):
            obj = world.find_object(name)
            return obj["id"] if obj else None
        plan = _heuristic_object_plan(world, here_id, name)
        if not plan:
            return None
        apply_patches(
            world, plan, kind="expand_location", allow=LOCATION_WRITER_OPS
        )
        found = world.find_object(name)
        return found["id"] if found else None

    def insert(self, world: World, text: str) -> dict[str, Any]:
        hit = world.find_actor(text)
        t = text.lower()
        kill = any(w in t or w in text for w in ("kill", "死", "殺"))
        injure = any(w in t or w in text for w in ("injure", "傷", "hurt", "臂", "腿"))
        if hit and kill:
            plan = StorytellerPlan(
                summary=text.strip(),
                patches=[
                    Patch(op="kill_actor", actor_id=hit["id"], detail=text.strip())
                ],
            )
        elif hit and injure:
            plan = StorytellerPlan(
                summary=text.strip(),
                patches=[
                    Patch(
                        op="edit_actor",
                        actor_id=hit["id"],
                        detail=text.strip(),
                        condition=text.strip()[:40],
                    )
                ],
            )
        elif hit:
            plan = StorytellerPlan(
                summary=text.strip(),
                patches=[
                    Patch(
                        op="edit_actor",
                        actor_id=hit["id"],
                        detail=text.strip(),
                    )
                ],
            )
        else:
            home = world.cx.execute(
                "SELECT id FROM locations ORDER BY id LIMIT 1"
            ).fetchone()
            here = home["id"] if home else ""
            name = text.strip()[:40] or "路人"
            plan = _heuristic_person_plan(world, here, name) or StorytellerPlan(
                summary="找不到可寫的人物。", patches=[]
            )
        if self.llm.mode == "live":
            from playout.agents.model import llm_mode, openrouter_model, strong_model_name
            from pydantic_ai import Agent

            if llm_mode() == "live":
                people = [
                    {"id": a["id"], "name": a["name"]}
                    for a in world.cx.execute("SELECT id,name FROM actors")
                ]
                user = f"意圖：{text}\n人物：{people}\n上限：{MAX_ACTORS}"
                agent: Agent[None, StorytellerPlan] = Agent(
                    openrouter_model(strong_model_name()),
                    output_type=StorytellerPlan,
                    instructions=ACTOR_WRITER_SYSTEM,
                )
                try:
                    out = agent.run_sync(user)
                    if isinstance(out.output, StorytellerPlan) and out.output.patches:
                        plan = out.output
                except Exception:
                    pass
        if not plan.patches:
            return {"ok": False, "summary": plan.summary, "patches": []}
        eid = apply_patches(world, plan, kind="god_actor", allow=ACTOR_WRITER_OPS)
        world.set_meta("idle_scenes", "0")
        world.cx.commit()
        return {
            "ok": True,
            "event_id": eid,
            "summary": plan.summary,
            "patches": [p.model_dump() for p in plan.patches],
        }

    def draft(self, setup: StorySetup, extras: list[ActorSetup]) -> StorySetup:
        actors = list(setup.actors)
        used = {a.id for a in actors}
        loc_ids = {loc.id for loc in setup.locations}
        home = setup.locations[0].id if setup.locations else ""
        for act in extras:
            if len(actors) >= MAX_ACTORS:
                break
            if act.id in used:
                continue
            place = act.location if act.location in loc_ids else home
            actors.append(act.model_copy(update={"location": place}))
            used.add(act.id)
        return setup.model_copy(update={"actors": actors})


def resolve_move(world: World, intent: "MoveIntent", llm: LLM | None = None):
    from playout.models import MoveIntent
    from playout.movement import apply_move

    matched = world.find_location(intent.to)
    if matched:
        return apply_move(world, intent.model_copy(update={"to": matched["id"]}))
    if intent.kind != "voluntary":
        return apply_move(world, intent)
    origin = world.actor(intent.actor_id)["location_id"]
    created = LocationWriter(llm).materialize_place(
        world, origin, intent.to, intent.actor_id
    )
    if created:
        return apply_move(world, intent.model_copy(update={"to": created}))
    return apply_move(world, intent)


def guess_unknown_person(world: World, text: str) -> str | None:
    if world.find_actor(text):
        return None
    for c in ("店員", "掌櫃", "老闆", "路人", "客人", "小廝"):
        if c in text and not world.find_actor(c):
            return c
    markers = ("找", "叫", "問", "對")
    if not any(m in text for m in markers):
        return None
    t = text.strip()
    for m in ("找", "去找", "叫", "問", "對"):
        t = t.replace(m, " ")
    t = t.replace("道", " ").replace("說", " ").strip(" 。，、：:「」 ")
    if world.find_actor(t) or world.find_location(t) or world.find_object(t):
        return None
    if is_vague_place(t) or len(t) < 2 or len(t) > 12:
        return None
    return t


def guess_unknown_object(world: World, text: str) -> str | None:
    if world.find_object(text):
        return None
    markers = ("拿", "取", "看", "察", "撿", "摸")
    if not any(m in text for m in markers):
        return None
    t = text.strip()
    for m in markers:
        t = t.replace(m, " ")
    t = t.strip(" 。，、：:「」")
    if world.find_object(t) or world.find_actor(t) or world.find_location(t):
        return None
    if is_vague_place(t) or len(t) < 2 or len(t) > 12:
        return None
    return t
