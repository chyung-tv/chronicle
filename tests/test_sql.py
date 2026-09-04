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


def _fake_psycopg(monkeypatch, seen: dict):
    import sys
    import types

    class FakeConn:
        def __init__(self):
            self.sql: list[str] = []
            self.commits = 0

        def execute(self, sql, *a, **k):
            self.sql.append(str(sql))
            return self

        def commit(self):
            self.commits += 1

        def close(self):
            pass

    def fake_connect(dsn, row_factory=None, autocommit=False):
        seen["autocommit"] = autocommit
        seen["dsn"] = dsn
        seen["conn"] = FakeConn()
        return seen["conn"]

    class SQL:
        def __init__(self, text):
            self.text = text

        def format(self, ident):
            return self.text.replace("{}", str(ident))

    fake_rows = types.ModuleType("psycopg.rows")
    fake_rows.dict_row = object()
    fake_sql = types.ModuleType("psycopg.sql")
    fake_sql.Identifier = lambda name: name
    fake_sql.SQL = SQL
    fake_psycopg = types.ModuleType("psycopg")
    fake_psycopg.connect = fake_connect
    fake_psycopg.sql = fake_sql
    fake_psycopg.rows = fake_rows
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setitem(sys.modules, "psycopg.sql", fake_sql)
    monkeypatch.setitem(sys.modules, "psycopg.rows", fake_rows)


def test_readonly_postgres_autocommit_and_timeouts(monkeypatch):
    seen: dict = {}
    _fake_psycopg(monkeypatch, seen)
    from playout.sql import connect_postgres

    cx = connect_postgres(
        schema="story_abc", readonly=True, url="postgresql://example"
    )
    assert seen["autocommit"] is True
    joined = " ".join(seen["conn"].sql)
    assert "lock_timeout" in joined
    assert "statement_timeout" in joined
    assert "default_transaction_read_only" in joined
    assert seen["conn"].commits == 0
    cx.close()


def test_write_postgres_commits_session_setup(monkeypatch):
    seen: dict = {}
    _fake_psycopg(monkeypatch, seen)
    from playout.sql import connect_postgres

    connect_postgres(schema="public", readonly=False, url="postgresql://example")
    assert seen["autocommit"] is False
    assert seen["conn"].commits == 1
