"""Taiwan Traditional Chinese literary register for prose, tape, and prompts."""

PROSE = (
    "一律使用台灣繁體中文書面語。"
    "敘事、事件摘要、日記、感知、章回用書面；對白可帶口吻，但勿網路腔、勿簡體、勿英譯腔。"
    "JSON 的鍵名與 action type、location_id、actor_id 保持英文；字串值用繁體中文。"
)


def with_prose(system: str) -> str:
    return PROSE + "\n\n" + system
