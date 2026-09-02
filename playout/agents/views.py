"""Pydantic read-models. Agents read these; SQLite remains sealed canon."""

from __future__ import annotations

from pydantic import BaseModel, Field

from playout.canon import World
from playout.memory import retrieve


class ObjectView(BaseModel):
    id: str
    name: str
    description: str = ""


class PersonView(BaseModel):
    id: str
    name: str
    injured: bool = False
    alive: bool = True


class RelationView(BaseModel):
    id: str
    name: str
    trust: int = 0
    resentment: int = 0
    notes: str = ""


class ActorView(BaseModel):
    """What one living person may know about themselves and this room."""

    id: str
    name: str
    voice: str = ""
    constitution: str = ""
    want: str = ""
    secret: str = ""
    goal: str = ""
    mood: str = ""
    injured: bool = False
    alive: bool = True
    location_id: str
    location_name: str
    location_description: str
    location_intact: bool = True
    present: list[PersonView] = Field(default_factory=list)
    visible_objects: list[ObjectView] = Field(default_factory=list)
    inventory: list[ObjectView] = Field(default_factory=list)
    adjacent: list[str] = Field(default_factory=list)
    relations: list[RelationView] = Field(default_factory=list)
    perceptions: list[str] = Field(default_factory=list)
    memories: list[str] = Field(default_factory=list)
    reflections: list[str] = Field(default_factory=list)


class WorldView(BaseModel):
    title: str = ""
    worldview: str = ""
    day: int = 1
    beat: str = ""
    weather: str = ""
    clock: str = ""


def world_view(world: World) -> WorldView:
    return WorldView(
        title=world.meta("title") or "",
        worldview=world.meta("worldview") or "",
        day=world.day,
        beat=world.beat_label,
        weather=world.meta("weather") or "",
        clock=world.meta("clock") or "",
    )


def actor_view(world: World, actor_id: str, extra: str = "") -> ActorView:
    a = world.actor(actor_id)
    loc = world.location(a["location_id"])
    others = [x for x in world.actors_at(a["location_id"]) if x["id"] != actor_id]
    adj = []
    for aid in world.adjacent(a["location_id"]):
        dest = world.location(aid)
        adj.append(f"{aid}（{dest['name']}）")
    rels: list[RelationView] = []
    for o in world.living_actors():
        if o["id"] == actor_id:
            continue
        r = world.relationship(actor_id, o["id"])
        if r:
            rels.append(
                RelationView(
                    id=o["id"],
                    name=o["name"],
                    trust=r["trust"],
                    resentment=r["resentment"],
                    notes=r["notes"],
                )
            )
    query = extra or a["goal"]
    return ActorView(
        id=a["id"],
        name=a["name"],
        voice=a["voice"],
        constitution=a["constitution"],
        want=a["want"],
        secret=a["secret"],
        goal=a["goal"],
        mood=a["mood"],
        injured=bool(a["injured"]),
        alive=bool(a["alive"]),
        location_id=a["location_id"],
        location_name=loc["name"],
        location_description=loc["description"],
        location_intact=bool(loc["intact"]),
        present=[
            PersonView(
                id=o["id"],
                name=o["name"],
                injured=bool(o["injured"]),
                alive=bool(o["alive"]),
            )
            for o in others
        ],
        visible_objects=[
            ObjectView(id=o["id"], name=o["name"], description=o["description"])
            for o in world.visible_objects(a["location_id"])
        ],
        inventory=[
            ObjectView(id=o["id"], name=o["name"], description=o["description"])
            for o in world.inventory(actor_id)
        ],
        adjacent=adj,
        relations=rels,
        perceptions=[
            f"第{p['day']}日 {p['text']}" for p in world.perceptions_for(actor_id, limit=12)
        ],
        memories=retrieve(world, actor_id, query),
        reflections=[r["text"] for r in world.reflections_for(actor_id, limit=3)],
    )


def view_as_prompt(world: World, actor_id: str, extra: str = "") -> str:
    w = world_view(world)
    a = actor_view(world, actor_id, extra)
    people = (
        "、".join(
            f"{p.name}（{p.id}）" + ("，帶傷" if p.injured else "") for p in a.present
        )
        or "無人"
    )
    obj_s = "、".join(f"{o.name} [{o.id}]" for o in a.visible_objects) or "眼前無物"
    inv_s = "、".join(f"{o.name} [{o.id}]" for o in a.inventory) or "空手"
    perc_s = "\n".join(f"- {p}" for p in a.perceptions[:10]) or "- （尚無）"
    mem_s = "\n".join(f"- {m}" for m in a.memories) or "- （日記空白）"
    ref_s = "\n".join(f"- {r}" for r in a.reflections) or "- （無）"
    rel_s = (
        "\n".join(
            f"{r.name}（{r.id}）：信 {r.trust}，怨 {r.resentment}。{r.notes}"
            for r in a.relations
        )
        or "（淡）"
    )
    return f"""世界：{w.title}。{w.worldview}
時辰：{w.beat}。天色：{w.weather}。
期限：{w.clock}

你是：{a.name}（{a.id}）
口吻：{a.voice}
本性（不變）：{a.constitution}
深願：{a.want}
你的秘密（他人不知，除非已聞）：{a.secret}
眼前之願（屬你）：{a.goal}
心境：{a.mood}
帶傷：{a.injured}

此地：{a.location_name}（{a.location_id}）。{a.location_description}
完好：{a.location_intact}
在場：{people}
可見之物：{obj_s}
隨身：{inv_s}
相鄰：{", ".join(a.adjacent) or "無"}

關係：
{rel_s}

近時感知（你真正見聞）：
{perc_s}

憶起的日記：
{mem_s}

省思：
{ref_s}

{extra}
"""
