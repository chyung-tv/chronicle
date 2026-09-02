"""Recency + importance + token overlap. No vector store in v1."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playout.canon import World

_WORD = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def retrieve(world: World, actor_id: str, query: str, k: int = 8) -> list[str]:
    rows = world.diary_for(actor_id, limit=40)
    q = _tokens(query)
    scored: list[tuple[float, str]] = []
    n = len(rows)
    for i, row in enumerate(rows):
        recency = 1.0 - (i / max(n, 1))
        importance = row["importance"] / 10.0
        overlap = len(q & _tokens(row["text"])) / max(len(q), 1)
        score = 0.5 * recency + 0.3 * importance + 0.2 * overlap
        scored.append((score, f"Day {row['day']} {row['text']}"))
    scored.sort(reverse=True)
    return [t for _, t in scored[:k]]
