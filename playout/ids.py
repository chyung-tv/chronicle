"""Stable ascii ids for locations, actors, and objects."""

from __future__ import annotations

import re

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

VAGUE_PLACE = frozenset(
    {
        "",
        "somewhere",
        "anywhere",
        "elsewhere",
        "here",
        "there",
        "某處",
        "別處",
        "那裡",
        "那裏",
        "那邊",
        "這里",
        "這裡",
        "這邊",
        "那地方",
        "一個地方",
        "外面",
        "遠方",
    }
)


def slugify(name: str, prefix: str, used: set[str]) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    if not _ID_RE.match(text):
        text = prefix
    base = text
    n = 1
    while text in used:
        n += 1
        text = f"{base}{n}"
    used.add(text)
    return text


def is_vague_place(text: str) -> bool:
    t = (text or "").strip().lower()
    if t in VAGUE_PLACE:
        return True
    if len(t) < 2:
        return True
    return False
