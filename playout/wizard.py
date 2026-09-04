"""Story wizard: enrich a human StorySketch into engine StorySetup."""

from __future__ import annotations

import re
from collections.abc import Callable
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
- 尊重速寫：不改原有人物與地點的 id、座標、與路。不可刪原有人物或地點。
- 為每人補 name（若空）、voice、want、secret、constitution、goal、mood。
- 為每處補 name（若空）與 description。
- 若原有人物少於 8、地點少於 8，可增添少數配角或側景（新 id），讓世界更厚。已滿則只豐富，不新增。
- 可把開場情勢與開場事件寫得更具體，但不要加完結日數或倒數。
- 沒有壓力與衝突，演繹容易變成日復一日的早飯戲。若速寫安靜，仍可安靜，只把世界寫清楚。
- 不要注入別的故事的人名或颱風、舢板，除非速寫裡已有。
- 物件：若速寫已列物件，只豐富它們。若物件清單為空而速寫提到具體物，可新增少數物件。新側景上也可放物件。
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
    extra_locs = [loc for loc in drafted.locations if loc.id not in loc_ids]
    if extra_locs:
        from playout.agents.expand import LocationWriter

        tmp = StorySetup(
            title=sketch.title or drafted.title,
            locations=locations,
            edges=[(a, b) for a, b in sketch.edges if a in loc_ids and b in loc_ids],
            actors=[
                ActorSetup(
                    id=act.id,
                    name=act.name or act.id,
                    location=act.location if act.location in loc_ids else locations[0].id,
                    want=act.note or "尚未定願。",
                    constitution=act.note or "尚未定性。",
                )
                for act in sketch.actors
            ],
        )
        tmp = LocationWriter().draft(tmp, extra_locs)
        locations = tmp.locations
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
    extra_acts = [act for act in drafted.actors if act.id not in actor_ids]
    if extra_acts:
        from playout.agents.expand import ActorWriter

        tmp_setup = StorySetup(
            title=sketch.title or drafted.title,
            locations=locations,
            edges=[(a, b) for a, b in sketch.edges if a in loc_ids and b in loc_ids],
            actors=actors,
        )
        tmp_setup = ActorWriter().draft(tmp_setup, extra_acts)
        actors = tmp_setup.actors
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
    have_obj = {o.id for o in objects}
    for obj in drafted.objects:
        if obj.id in have_obj:
            continue
        if obj.location_id and obj.location_id not in loc_ids:
            continue
        if obj.holder_id and obj.holder_id not in actor_ids:
            continue
        objects.append(obj)
        have_obj.add(obj.id)
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
    have_rel = {(r.a, r.b) for r in rels}
    for rel in drafted.relationships:
        if (rel.a, rel.b) in have_rel:
            continue
        if rel.a in actor_ids and rel.b in actor_ids:
            rels.append(rel)
            have_rel.add((rel.a, rel.b))
    edges = [(a, b) for a, b in sketch.edges if a in loc_ids and b in loc_ids]
    seen_edges = {tuple(sorted(e)) for e in edges}
    for a, b in drafted.edges:
        if a not in loc_ids or b not in loc_ids:
            continue
        key = tuple(sorted((a, b)))
        if key in seen_edges:
            continue
        edges.append((a, b))
        seen_edges.add(key)
    extra_loc_ids = loc_ids - {loc.id for loc in sketch.locations}
    home = locations[0].id
    for loc_id in extra_loc_ids:
        linked = any(a == loc_id or b == loc_id for a, b in edges)
        if not linked and loc_id != home:
            edges.append((home, loc_id))
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


def enrich(
    sketch: StorySketch,
    llm: LLM | None = None,
    on_progress: Callable[[str, float], None] | None = None,
) -> StorySetup:
    llm = llm or LLM()
    if llm.mode != "live":
        if on_progress:
            on_progress("正在核對設定", 0.7)
        return mock_enrich(sketch)
    if on_progress:
        on_progress("正在請示語言模型", 0.4)
    data: dict[str, Any] = llm.complete_json(
        WIZARD_SYSTEM, _user_payload(sketch), strong=True
    )
    try:
        drafted = StorySetup.model_validate(_coerce_draft(data, sketch))
        if on_progress:
            on_progress("正在核對設定", 0.75)
        return stitch(sketch, drafted)
    except Exception:
        if on_progress:
            on_progress("正在請示語言模型", 0.55)
        data2 = llm.complete_json(
            WIZARD_SYSTEM,
            _user_payload(sketch) + "\n\n只回傳合法 JSON。保留原有 id。配角與側景可用新 id。",
            strong=True,
        )
        drafted = StorySetup.model_validate(_coerce_draft(data2, sketch))
        if on_progress:
            on_progress("正在核對設定", 0.75)
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
    loc_ids = {loc.id for loc in sketch.locations}
    actor_ids = {a.id for a in sketch.actors}
    for loc in data.get("locations") or []:
        if isinstance(loc, dict) and _ID_RE.match(str(loc.get("id") or "")):
            loc_ids.add(str(loc["id"]))
    for act in data.get("actors") or []:
        if isinstance(act, dict) and _ID_RE.match(str(act.get("id") or "")):
            actor_ids.add(str(act["id"]))
    data["objects"] = _sanitize_objects(
        data.get("objects") or [], sketch, loc_ids=loc_ids, actor_ids=actor_ids
    )
    data["turns_per_day_min"] = len(sketch.actors)
    data["turns_per_day_max"] = sketch.turns_per_day_max
    return data


_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _next_obj_id(used: set[str]) -> str:
    n = 1
    while f"obj{n}" in used:
        n += 1
    return f"obj{n}"


def _sanitize_id(raw: Any, used: set[str]) -> str:
    text = re.sub(r"[^a-z0-9_]+", "_", str(raw or "").lower()).strip("_")
    if not _ID_RE.match(text):
        text = _next_obj_id(used)
    if text in used:
        text = _next_obj_id(used)
    used.add(text)
    return text


def _sanitize_objects(
    objs: list[Any],
    sketch: StorySketch,
    *,
    loc_ids: set[str] | None = None,
    actor_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    used = {o.id for o in sketch.objects}
    loc_ids = loc_ids if loc_ids is not None else {loc.id for loc in sketch.locations}
    actor_ids = actor_ids if actor_ids is not None else {a.id for a in sketch.actors}
    out: list[dict[str, Any]] = []
    for obj in objs:
        if not isinstance(obj, dict):
            continue
        oid = str(obj.get("id") or "")
        if oid in used and oid in {o.id for o in sketch.objects}:
            used.add(oid)
        else:
            oid = _sanitize_id(oid, used)
        loc = obj.get("location_id")
        holder = obj.get("holder_id")
        out.append(
            {
                **obj,
                "id": oid,
                "name": obj.get("name") or oid,
                "location_id": loc if loc in loc_ids else None,
                "holder_id": holder if holder in actor_ids else None,
            }
        )
    return out
