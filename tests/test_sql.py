from playout.sql import qmark_to_percent, schema_name, story_source


def test_schema_name_uuid():
    sid = "01234567-89ab-cdef-0123-456789abcdef"
    assert schema_name(sid) == "story_0123456789abcdef0123456789abcdef"


def test_schema_name_slug():
    assert schema_name("Harbor's End") == "story_harbor_s_end"


def test_story_source():
    assert story_source("abc").startswith("postgresql:story:")


def test_qmark_to_percent():
    sql = "SELECT * FROM stories WHERE id=? OR slug=?"
    assert qmark_to_percent(sql) == "SELECT * FROM stories WHERE id=%s OR slug=%s"
