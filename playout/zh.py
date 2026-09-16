"""Hong Kong written Chinese register for prose, tape, and prompts."""

PROSE = (
    "一律使用香港繁體中文書面語。"
    "敘事、事件摘要、日記、感知、章節：現代香港書面，短句、清楚、當下，像報章副刊或當代小說。"
    "不要章回體，不要文言，不要「且說」「正是」；旁述不要用「道：『』」。"
    "對白可以帶香港口語味道，但正文與旁述仍用書面，不要把整段寫成粵語口語入文。"
    "不要網絡潮語、不要簡體、不要英譯腔。"
    "JSON 的鍵名與 action type、location_id、actor_id 保持英文；字串值用繁體中文。"
)

VOICE_UNSET = "聲線未定。"
WANT_UNSET = "意願未定。"
NATURE_UNSET = "性格未定。"
DESC_UNSET = "暫時未有描述。"
MOOD_DEFAULT = "靜"


def with_prose(system: str) -> str:
    return PROSE + "\n\n" + system


def say(speaker: str, line: str, hearer: str | None = None) -> str:
    """Tape and perception speech in house 書面: 說, not 章回 道."""
    if hearer:
        return f"{speaker}對{hearer}說：「{line}」"
    return f"{speaker}說：「{line}」"
