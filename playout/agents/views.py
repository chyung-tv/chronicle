"""Pydantic read-models. Agents read these; SQLite remains sealed canon."""

from __future__ import annotations

from pydantic import BaseModel, Field

from playout.canon import World
from playout.memory import retrieve
from playout.models import LocationNode, WorldAtmosphere


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
    location: LocationNode
    inventory: list[ObjectView] = Field(default_factory=list)
    relations: list[RelationView] = Field(default_factory=list)
    perceptions: list[str] = Field(default_factory=list)
    memories: list[str] = Field(default_factory=list)
    reflections: list[str] = Field(default_factory=list)

    @property
    def location_id(self) -> str:
        return self.location.id


class WorldView(WorldAtmosphere):
    """Alias: atmosphere is the non-spatial world."""


def world_view(world: World) -> WorldAtmosphere:
    return world.atmosphere()


def actor_view(world: World, actor_id: str, extra: str = "") -> ActorView:
    a = world.actor(actor_id)
    node = world.node(a["location_id"])
    present_self = [p for p in node.present if p.id != actor_id]
    node = node.model_copy(update={"present": present_self})
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
        location=node,
        inventory=[
            ObjectView(id=o["id"], name=o["name"], description=o["description"])
            for o in world.inventory(actor_id)
        ],
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
    loc = a.location
    people = (
        "、".join(
            f"{p.name}（{p.id}）" + ("，帶傷" if p.injured else "") for p in loc.present
        )
        or "無人"
    )
    obj_s = "、".join(f"{o.name} [{o.id}]" for o in loc.visible_objects) or "眼前無物"
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
    exits = [
        f"{e.id}（{e.name}）" + ("" if e.intact else "，已毀不可入")
        for e in loc.connected
    ]
    walkable = [e.id for e in loc.connected if e.intact]
    return f"""世界：{w.title}。{w.worldview}
時辰：{w.beat}。天色：{w.weather}。
開局：{w.clock}

你是：{a.name}（{a.id}）
口吻：{a.voice}
本性（不變）：{a.constitution}
深願：{a.want}
你的秘密（他人不知，除非已聞）：{a.secret}
眼前之願（屬你）：{a.goal}
心境：{a.mood}
帶傷：{a.injured}

此地：{loc.name}（{loc.id}）。{loc.description}
完好：{loc.intact}
在場：{people}
可見之物：{obj_s}
隨身：{inv_s}
相鄰：{", ".join(exits) or "無"}
可走（move 的 to）：{", ".join(walkable) or "無"}

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
