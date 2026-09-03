"""Writer: sifts the day's event tape into a chapter. Consume-only. Grounded on event ids."""

from __future__ import annotations

import json
from typing import Any

from playout.canon import World
from playout.llm import LLM
from playout.models import WriterChapter
from playout.zh import with_prose

WRITER_SYSTEM = with_prose("""你是小說家，重述一份模擬日誌。可以壓縮、略過早飯、選定一個視角。
不可捏造日誌裡沒有的事件、死亡、親吻、發現或對白。
每一樁事實都須能被所引的 event id 支撐。
當日無人死，就不要寫死；當日有死，照實寫，不必迴避。
有 payload.speeches 時，寫成「甲對乙道：「…」」。用詞可稍加打磨，意思與引號內的話不可改。
沒有記錄下來的台詞，才可改寫成招呼、點頭之類。
可就「地點」裡已有的環境描寫與當天天色加以渲染（潮、風、氣味、泥）。不可添該地描述與事件帶都沒有的物件、足跡或房間。

只回傳 JSON：
{"pov":"<actor_id>","tags":["背叛","颱風"],"cited_event_ids":[1,2,3],"text":"章回正文，繁體中文書面，約四百至八百字"}
""")


def _sift_tags(summaries: list[str]) -> list[str]:
    blob = " ".join(summaries).lower()
    tags = []
    for tag, keys in {
        "暴力": ["attack", "kill", "injured", "襲擊", "殺", "傷"],
        "發現": ["examines", "letter", "finds", "searches", "察看", "信", "搜"],
        "離去": ["goes to", "前往"],
        "對談": ["對", "道：「"],
        "世變": ["storm", "meteor", "ruined", "颱風", "隕石", "已毀"],
        "導引": ["motive", "weapon", "alone", "動機", "刀", "獨處"],
    }.items():
        if any(k in blob for k in keys):
            tags.append(tag)
    return tags or ["日常"]


def _parse_payload(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def writer_pack(world: World, day: int) -> dict[str, Any]:
    """Tape plus location palettes the novelist may thicken."""
    events = world.events_for_day(day)
    tape: list[dict[str, Any]] = []
    touched: set[str] = set()
    for e in events:
        payload = _parse_payload(e["payload"] if "payload" in e.keys() else "{}")
        row = {
            "id": e["id"],
            "kind": e["kind"],
            "summary": e["summary"],
            "actor_id": e["actor_id"],
            "target_id": e["target_id"],
            "payload": payload,
        }
        tape.append(row)
        for key in ("from", "to", "location_id"):
            loc = payload.get(key)
            if loc:
                touched.add(str(loc))
        if e["actor_id"]:
            try:
                touched.add(world.actor(e["actor_id"])["location_id"])
            except Exception:
                pass
    nodes = []
    for loc_id in sorted(touched):
        try:
            node = world.node(loc_id)
        except Exception:
            continue
        nodes.append(
            {"id": node.id, "name": node.name, "description": node.description}
        )
    atmo = world.atmosphere()
    return {
        "tape": tape,
        "locations": nodes,
        "weather": atmo.weather,
        "clock": atmo.clock,
        "beat": atmo.beat,
    }


def _heuristic_chapter(world: World, day: int, events: list) -> WriterChapter:
    living = [a for a in world.living_actors()]
    pov = living[day % len(living)]["id"] if living else "lena"
    pov_name = world.actor(pov)["name"] if living else "有人"
    lines = []
    cited = []
    skip_kinds = {"wait"}
    for e in events:
        if e["kind"] in skip_kinds:
            continue
        cited.append(e["id"])
        payload = _parse_payload(e["payload"] if "payload" in e.keys() else "{}")
        speeches = payload.get("speeches") or []
        if speeches:
            bits = []
            for sp in speeches:
                speaker_id = sp.get("speaker_id")
                try:
                    speaker = world.actor(speaker_id)["name"] if speaker_id else "有人"
                except Exception:
                    speaker = speaker_id or "有人"
                hearer_id = sp.get("hearer_id")
                line = sp.get("text") or ""
                if hearer_id:
                    try:
                        hearer = world.actor(hearer_id)["name"]
                    except Exception:
                        hearer = hearer_id
                    bits.append(f"{speaker}對{hearer}道：「{line}」")
                else:
                    bits.append(f"{speaker}道：「{line}」")
            lines.append(" ".join(bits))
        else:
            lines.append(f"{e['summary']}")
    tags = _sift_tags([e["summary"] for e in events])
    if not lines:
        text = (
            f"{pov_name}度過第{day}日一段無事的光陰。天色憋著。無事可記，因為無事發生。"
        )
    else:
        body = " ".join(lines[:18])
        text = (
            f"第{day}日，從{pov_name}這一側看。\n\n"
            f"鎮不為誰停。{body}\n\n"
            f"發生的，便已發生。其餘是天色。"
        )
    return WriterChapter(pov=pov, tags=tags, cited_event_ids=cited, text=text)


def validate_chapter(world: World, day: int, chapter: WriterChapter) -> WriterChapter:
    events = {e["id"]: e for e in world.events_for_day(day)}
    cited = [i for i in chapter.cited_event_ids if i in events]
    if not cited:
        cited = [e["id"] for e in world.events_for_day(day) if e["kind"] != "wait"]
    chapter.cited_event_ids = cited
    return chapter


def write_day(world: World, llm: LLM, day: int) -> dict[str, Any]:
    events = world.events_for_day(day)
    pack = writer_pack(world, day)
    if llm.mode == "live" and pack["tape"]:
        actors = [
            {"id": a["id"], "name": a["name"]}
            for a in world.cx.execute("SELECT id,name FROM actors")
        ]
        user = (
            f"第{day}日事件帶（正史）：\n{pack['tape']}\n"
            f"人物：{actors}\n"
            f"地點（可渲染的環境）：{pack['locations']}\n"
            f"天色：{pack['weather']}\n期限：{pack['clock']}"
        )
        data = llm.complete_json(WRITER_SYSTEM, user, strong=True)
        try:
            chapter = WriterChapter.model_validate(data)
        except Exception:
            chapter = _heuristic_chapter(world, day, events)
    else:
        chapter = _heuristic_chapter(world, day, events)
    chapter = validate_chapter(world, day, chapter)
    cid = world.write_chapter(
        day, chapter.pov, chapter.text, chapter.tags, chapter.cited_event_ids
    )
    return {"chapter_id": cid, **chapter.model_dump()}
