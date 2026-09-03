from playout.sql import adapt_postgres_sql, qmark_to_percent, schema_name, story_source


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


def test_insert_or_ignore():
    out = adapt_postgres_sql("INSERT OR IGNORE INTO edges(a, b) VALUES(?,?)")
    assert "ON CONFLICT DO NOTHING" in out
    assert "%s" in out
