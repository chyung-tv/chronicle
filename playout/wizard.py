"""Story wizard: enrich a human StorySketch into engine StorySetup."""

from __future__ import annotations

from typing import Any

from playout.llm import LLM
from playout.models import (
    MAX_TURNS_PER_DAY,
    ActorSetup,
    LocationSetup,
    ObjectSetup,
    RelationshipSetup,
    StorySetup,
    StorySketch,
)
from playout.zh import with_prose

WIZARD_SYSTEM = with_prose("""你是故事巫師。人交來一份速寫（地名、人物一句話、開局兩段）。你把它補成可開演的世界設定。

規則：
- 只回傳 JSON，繁體中文。
- 尊重速寫：不改人物與地點的數量與 id，不改座標，不改路（edges）。
- 為每人補 name（若空）、voice、want、secret、constitution、goal、mood。
- 為每處補 name（若空）與 description。
- 可把開場情勢與開場事件寫得更具體，但不要加完結日數或倒數。
- 沒有壓力與衝突，演繹容易變成日復一日的早飯戲。若速寫安靜，仍可安靜，只把世界寫清楚。
- 不要注入別的故事的人名或颱風、舢板，除非速寫裡已有。
- 物件：若速寫已列物件，只豐富它們。若物件清單為空而速寫提到具體物，可新增少數物件。
- 關係：可從速寫推斷 trust / resentment / notes。

JSON 形狀：
{
  "title": "...",
  "worldview": "...",
  "opening_situation": "...",
  "opening_events": "...",
  "locations": [{"id":"...","name":"...","description":"...","x":0,"y":0}],
  "edges": [["a","b"]],
  "actors": [{"id":"...","name":"...","location":"...","voice":"...","want":"...","secret":"...","constitution":"...","goal":"...","mood":"靜"}],
  "objects": [{"id":"...","name":"...","description":"...","location_id":null,"holder_id":null,"hidden":false}],
  "relationships": [{"a":"...","b":"...","trust":0,"resentment":0,"notes":"..."}]
}
""")


def stitch(sketch: StorySketch, drafted: StorySetup) -> StorySetup:
    """Force deterministic knobs from the sketch onto wizard output."""
    loc_by_id = {loc.id: loc for loc in drafted.locations}
    act_by_id = {act.id: act for act in drafted.actors}
    locations: list[LocationSetup] = []
    for loc in sketch.locations:
        filled = loc_by_id.get(loc.id)
        locations.append(
            LocationSetup(
                id=loc.id,
                name=(filled.name if filled and filled.name else loc.name) or loc.id,
                description=(filled.description if filled else "") or loc.note or "尚無描述。",
                x=loc.x,
                y=loc.y,
            )
        )
    loc_ids = {loc.id for loc in locations}
    home = locations[0].id
    actors: list[ActorSetup] = []
    for act in sketch.actors:
        filled = act_by_id.get(act.id)
        place = act.location if act.location in loc_ids else home
        name = (filled.name if filled and filled.name else act.name) or act.id
        want = (filled.want if filled else "") or act.note or "尚未定願。"
        actors.append(
            ActorSetup(
                id=act.id,
                name=name,
                location=place,
                voice=(filled.voice if filled else "") or "尚未定腔。",
                want=want,
                secret=(filled.secret if filled else "") or "",
                constitution=(filled.constitution if filled else "") or (act.note or "尚未定性。"),
                goal=(filled.goal if filled else "") or want,
                mood=(filled.mood if filled else "") or "靜",
            )
        )
    actor_ids = {a.id for a in actors}
    n = len(actors)
    hi = max(n, min(MAX_TURNS_PER_DAY, sketch.turns_per_day_max))
    objects: list[ObjectSetup] = []
    if sketch.objects:
        obj_by_id = {o.id: o for o in drafted.objects}
        for obj in sketch.objects:
            filled = obj_by_id.get(obj.id)
            objects.append(
                ObjectSetup(
                    id=obj.id,
                    name=(filled.name if filled and filled.name else obj.name) or obj.id,
                    description=(filled.description if filled else "") or obj.note or "",
                    location_id=obj.location_id
                    if obj.location_id in loc_ids
                    else (filled.location_id if filled else None),
                    holder_id=obj.holder_id
                    if obj.holder_id in actor_ids
                    else (filled.holder_id if filled else None),
                    hidden=filled.hidden if filled else False,
                )
            )
    else:
        for obj in drafted.objects:
            if obj.location_id and obj.location_id not in loc_ids:
                continue
            if obj.holder_id and obj.holder_id not in actor_ids:
                continue
            objects.append(obj)
    rels: list[RelationshipSetup] = []
    if sketch.relationships:
        rel_map = {(r.a, r.b): r for r in drafted.relationships}
        for rel in sketch.relationships:
            filled = rel_map.get((rel.a, rel.b))
            rels.append(
                RelationshipSetup(
                    a=rel.a,
                    b=rel.b,
                    trust=filled.trust if filled else 0,
                    resentment=filled.resentment if filled else 0,
                    notes=(filled.notes if filled else "") or rel.note,
                )
            )
    else:
        for rel in drafted.relationships:
            if rel.a in actor_ids and rel.b in actor_ids:
                rels.append(rel)
    edges = [(a, b) for a, b in sketch.edges if a in loc_ids and b in loc_ids]
    return StorySetup(
        title=sketch.title or drafted.title,
        turns_per_day_min=n,
        turns_per_day_max=hi,
        worldview=drafted.worldview or sketch.worldview,
        opening_situation=drafted.opening_situation or sketch.opening_situation,
        opening_events=drafted.opening_events or sketch.opening_events,
        locations=locations,
        edges=edges,
        actors=actors,
        objects=objects,
        relationships=rels,
    )


def mock_enrich(sketch: StorySketch) -> StorySetup:
    locations = [
        LocationSetup(
            id=loc.id,
            name=loc.name or loc.id,
            description=loc.note or f"{loc.name or loc.id}。尚待細寫。",
            x=loc.x,
            y=loc.y,
        )
        for loc in sketch.locations
    ]
    home = locations[0].id
    actors = []
    for act in sketch.actors:
        note = act.note or "尚未定願。"
        actors.append(
            ActorSetup(
                id=act.id,
                name=act.name or act.id,
                location=act.location or home,
                voice=f"{act.name or act.id}的口吻尚未定，只知：{note}",
                want=note,
                secret="",
                constitution=note,
                goal=note,
                mood="靜",
            )
        )
    objects = [
        ObjectSetup(
            id=obj.id,
            name=obj.name or obj.id,
            description=obj.note or "",
            location_id=obj.location_id,
            holder_id=obj.holder_id,
        )
        for obj in sketch.objects
    ]
    rels = [
        RelationshipSetup(a=rel.a, b=rel.b, notes=rel.note)
        for rel in sketch.relationships
    ]
    n = len(actors)
    drafted = StorySetup(
        title=sketch.title,
        turns_per_day_min=n,
        turns_per_day_max=sketch.turns_per_day_max,
        worldview=sketch.worldview or "這是一個尚待寫清的世界。世上無神異。",
        opening_situation=sketch.opening_situation,
        opening_events=sketch.opening_events,
        locations=locations,
        edges=list(sketch.edges),
        actors=actors,
        objects=objects,
        relationships=rels,
    )
    return stitch(sketch, drafted)


def _user_payload(sketch: StorySketch) -> str:
    import json

    return json.dumps(sketch.model_dump(mode="json"), ensure_ascii=False, indent=2)


def enrich(sketch: StorySketch, llm: LLM | None = None) -> StorySetup:
    llm = llm or LLM()
    if llm.mode != "live":
        return mock_enrich(sketch)
    data: dict[str, Any] = llm.complete_json(
        WIZARD_SYSTEM, _user_payload(sketch), strong=True
    )
    try:
        drafted = StorySetup.model_validate(_coerce_draft(data, sketch))
        return stitch(sketch, drafted)
    except Exception:
        data2 = llm.complete_json(
            WIZARD_SYSTEM,
            _user_payload(sketch) + "\n\n只回傳合法 JSON。勿增減人物或地點。",
            strong=True,
        )
        drafted = StorySetup.model_validate(_coerce_draft(data2, sketch))
        return stitch(sketch, drafted)


def _coerce_draft(data: dict[str, Any], sketch: StorySketch) -> dict[str, Any]:
    """Fill required ids from the sketch if the model omitted scaffolding."""
    if not data:
        data = {}
    data.setdefault("title", sketch.title)
    data.setdefault("worldview", sketch.worldview)
    data.setdefault("opening_situation", sketch.opening_situation)
    data.setdefault("opening_events", sketch.opening_events)
    data.setdefault("edges", [list(e) for e in sketch.edges])
    if not data.get("locations"):
        data["locations"] = [
            {
                "id": loc.id,
                "name": loc.name or loc.id,
                "description": loc.note,
                "x": loc.x,
                "y": loc.y,
            }
            for loc in sketch.locations
        ]
    if not data.get("actors"):
        data["actors"] = [
            {
                "id": act.id,
                "name": act.name or act.id,
                "location": act.location,
                "voice": act.note,
                "want": act.note,
                "constitution": act.note,
            }
            for act in sketch.actors
        ]
    data.setdefault("objects", [])
    data.setdefault("relationships", [])
    data["turns_per_day_min"] = len(sketch.actors)
    data["turns_per_day_max"] = sketch.turns_per_day_max
    return data
