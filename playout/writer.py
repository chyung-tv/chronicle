"""Writer: sifts the day's event tape into a chapter. Consume-only. Grounded on event ids."""

from __future__ import annotations

import re
from typing import Any

from playout.canon import World
from playout.llm import LLM
from playout.models import WriterChapter

WRITER_SYSTEM = """You are a novelist retelling a simulation log. You may compress, skip breakfast, choose one POV.
You may NOT invent events, deaths, kisses, discoveries, or dialogue that is not in the log.
Every factual beat must be supportable by a cited event id.
If nobody died, do not write a death.
If someone spoke, you may polish the wording slightly but keep the meaning.

Return JSON:
{"pov":"<actor_id>","tags":["betrayal","storm"],"cited_event_ids":[1,2,3],"text":"markdown chapter, 400-800 words"}
"""

DEATH_WORDS = re.compile(r"\b(killed|kills|murdered|dead|dies|died|corpse|body)\b", re.I)


def _sift_tags(summaries: list[str]) -> list[str]:
    blob = " ".join(summaries).lower()
    tags = []
    for tag, keys in {
        "violence": ["attack", "kill", "injured"],
        "discovery": ["examines", "letter", "finds", "searches"],
        "departure": ["goes to"],
        "talk": ["to "],
        "world": ["storm", "meteor", "ruined"],
        "steer": ["motive", "weapon", "alone"],
    }.items():
        if any(k in blob for k in keys):
            tags.append(tag)
    return tags or ["slice"]


def _heuristic_chapter(world: World, day: int, events: list) -> WriterChapter:
    living = [a for a in world.living_actors()]
    pov = living[day % len(living)]["id"] if living else "lena"
    pov_name = world.actor(pov)["name"] if living else "Someone"
    lines = []
    cited = []
    skip_kinds = {"wait"}
    for e in events:
        if e["kind"] in skip_kinds:
            continue
        cited.append(e["id"])
        lines.append(f"{e['summary']}")
    tags = _sift_tags([e["summary"] for e in events])
    if not lines:
        text = f"{pov_name} passes a quiet span of day {day}. The weather holds its breath. Nothing of note is written because nothing of note occurred."
    else:
        body = " ".join(lines[:18])
        text = (
            f"Day {day}, from {pov_name}'s side of the glass.\n\n"
            f"The town does not pause for anyone. {body}\n\n"
            f"What happened is what happened. The rest is weather."
        )
    return WriterChapter(pov=pov, tags=tags, cited_event_ids=cited, text=text)


def validate_chapter(world: World, day: int, chapter: WriterChapter) -> WriterChapter:
    events = {e["id"]: e for e in world.events_for_day(day)}
    cited = [i for i in chapter.cited_event_ids if i in events]
    if not cited:
        cited = [e["id"] for e in world.events_for_day(day) if e["kind"] != "wait"]
    chapter.cited_event_ids = cited
    deaths = world.death_events()
    death_ids = {e["id"] for e in deaths}
    day_death = any(e["day"] == day for e in deaths)
    if DEATH_WORDS.search(chapter.text) and not day_death and not (set(cited) & death_ids):
        # Strip invented death: rewrite last paragraph note rather than inventing.
        chapter.text = DEATH_WORDS.sub("fell silent", chapter.text)
        chapter.tags = [t for t in chapter.tags if t != "violence"] + ["grounded"]
    return chapter


def write_day(world: World, llm: LLM, day: int) -> dict[str, Any]:
    events = world.events_for_day(day)
    tape = [
        {
            "id": e["id"],
            "kind": e["kind"],
            "summary": e["summary"],
            "actor_id": e["actor_id"],
            "target_id": e["target_id"],
        }
        for e in events
    ]
    if llm.mode == "live" and tape:
        user = f"Day {day} event tape (canon):\n{tape}\nActors: {[{'id':a['id'],'name':a['name']} for a in world.cx.execute('SELECT id,name FROM actors')]}"
        data = llm.complete_json(WRITER_SYSTEM, user, strong=True)
        try:
            chapter = WriterChapter.model_validate(data)
        except Exception:
            chapter = _heuristic_chapter(world, day, events)
    else:
        chapter = _heuristic_chapter(world, day, events)
    chapter = validate_chapter(world, day, chapter)
    cid = world.write_chapter(day, chapter.pov, chapter.text, chapter.tags, chapter.cited_event_ids)
    return {"chapter_id": cid, **chapter.model_dump()}
