"""SQLite + Postgres connection helpers.

Local tests keep using SQLite files. Railway sets DATABASE_URL and the catalog
plus each story's sealed canon live in one Postgres database: catalog tables in
`public`, each live story in a schema named `story_<uuidhex>`.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Sequence

PG_STORY_PREFIX = "postgresql:story:"
_SCHEMA_OK = re.compile(r"^(public|story_[a-z0-9_]+)$")


def database_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("PLAYOUT_DATABASE_URL") or None


def is_postgres_source(source: str | Path) -> bool:
    return str(source).startswith(PG_STORY_PREFIX)


def story_id_from_source(source: str | Path) -> str:
    raw = str(source)
    if not raw.startswith(PG_STORY_PREFIX):
        raise ValueError(f"not a postgres story ref: {raw}")
    return raw[len(PG_STORY_PREFIX) :]


def story_source(story_id: str) -> str:
    return f"{PG_STORY_PREFIX}{story_id}"


def schema_name(story_id: str) -> str:
    hex_id = story_id.replace("-", "").lower()
    if re.fullmatch(r"[0-9a-f]{32}", hex_id):
        return f"story_{hex_id}"
    safe = re.sub(r"[^a-z0-9]+", "_", story_id.lower()).strip("_")[:40]
    return f"story_{safe or 'x'}"


def qmark_to_percent(sql: str) -> str:
    """Turn sqlite `?` placeholders into psycopg `%s`."""
    return sql.replace("?", "%s")


def adapt_postgres_sql(sql: str) -> str:
    """Sqlite-shaped SQL → Postgres (placeholders + INSERT OR IGNORE)."""
    ignore = bool(re.search(r"(?i)^\s*INSERT\s+OR\s+IGNORE\s+INTO\b", sql))
    stmt = re.sub(r"(?i)^\s*INSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql)
    stmt = qmark_to_percent(stmt)
    if ignore and "ON CONFLICT" not in stmt.upper():
        stmt = stmt.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return stmt


def insert_returning_id(cx: Any, sql: str, params: Sequence[Any] = ()) -> int:
    stmt = sql.strip().rstrip(";")
    if "RETURNING" not in stmt.upper():
        stmt = f"{stmt} RETURNING id"
    row = cx.execute(stmt, tuple(params)).fetchone()
    if row is None:
        raise RuntimeError("insert did not return id")
    return int(row["id"])


class PgRow:
    def __init__(self, data: dict[str, Any]):
        self._data = dict(data)
        self._keys = list(data.keys())

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._data[self._keys[key]]
        return self._data[key]

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def keys(self) -> Iterable[str]:
        return self._data.keys()


class PgCursor:
    def __init__(self, rows: list[PgRow], lastrowid: int | None):
        self._rows = rows
        self._i = 0
        self.lastrowid = lastrowid
        self.rowcount = len(rows)

    def fetchone(self) -> PgRow | None:
        if self._i >= len(self._rows):
            return None
        row = self._rows[self._i]
        self._i += 1
        return row

    def fetchall(self) -> list[PgRow]:
        rest = self._rows[self._i :]
        self._i = len(self._rows)
        return rest

    def __iter__(self):
        return iter(self.fetchall())


class PgConnection:
    def __init__(self, conn: Any):
        self._conn = conn
        self._lock = threading.RLock()
        self.row_factory = None

    def execute(self, sql: str, params: Sequence[Any] = ()) -> PgCursor:
        adapted = adapt_postgres_sql(sql)
        with self._lock:
            cur = self._conn.execute(adapted, tuple(params), prepare=False)
            if cur.description is None:
                return PgCursor([], None)
            raw = list(cur.fetchall())
            rows = [PgRow(dict(r) if not isinstance(r, dict) else r) for r in raw]
            last = None
            if rows and "id" in rows[0]:
                try:
                    last = int(rows[0]["id"])
                except (TypeError, ValueError):
                    last = None
            return PgCursor(rows, last)

    def executescript(self, script: str) -> None:
        for stmt in _split_sql(script):
            if stmt.strip():
                self.execute(stmt)

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    def rollback(self) -> None:
        with self._lock:
            self._conn.rollback()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def connect_sqlite(
    path: str | Path, *, readonly: bool = False, timeout: float = 5.0
) -> sqlite3.Connection:
    db_path = Path(path)
    if readonly:
        uri = db_path.resolve().as_uri() + "?mode=ro"
        cx = sqlite3.connect(uri, uri=True, timeout=timeout, check_same_thread=False)
        cx.row_factory = sqlite3.Row
        cx.execute("PRAGMA query_only=ON")
        return cx
    db_path.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(str(db_path), check_same_thread=False, timeout=timeout)
    cx.row_factory = sqlite3.Row
    return cx


def connect_postgres(
    *,
    schema: str = "public",
    readonly: bool = False,
    create_schema: bool = False,
    url: str | None = None,
) -> PgConnection:
    import psycopg
    from psycopg import sql as psql
    from psycopg.rows import dict_row

    dsn = url or database_url()
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    if not _SCHEMA_OK.match(schema):
        raise ValueError(f"unsafe schema name {schema!r}")
    # Readonly connections autocommit so SSE/state never sits idle-in-transaction
    # (that blocks ACCESS EXCLUSIVE DDL from a worker reopening the same schema).
    conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=readonly)
    ident = psql.Identifier(schema)
    if create_schema and schema != "public":
        conn.execute(psql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(ident))
        if not readonly:
            conn.commit()
    if schema != "public":
        conn.execute(
            psql.SQL("SET search_path TO {}, public").format(ident)
        )
    if readonly:
        conn.execute("SET default_transaction_read_only = on")
        conn.execute("SET lock_timeout = '3s'")
        conn.execute("SET statement_timeout = '8s'")
    if not readonly:
        conn.commit()
    return PgConnection(conn)


def drop_story_schema(story_id: str, *, url: str | None = None) -> None:
    import psycopg
    from psycopg import sql as psql

    dsn = url or database_url()
    if not dsn:
        return
    schema = schema_name(story_id)
    if not _SCHEMA_OK.match(schema):
        raise ValueError(f"unsafe schema name {schema!r}")
    conn = psycopg.connect(dsn, autocommit=True)
    try:
        conn.execute(
            psql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(psql.Identifier(schema))
        )
    finally:
        conn.close()


def schema_exists(story_id: str, *, url: str | None = None) -> bool:
    dsn = url or database_url()
    if not dsn:
        return False
    cx = connect_postgres(schema="public", url=dsn)
    try:
        row = cx.execute(
            "SELECT 1 AS ok FROM information_schema.schemata WHERE schema_name=?",
            (schema_name(story_id),),
        ).fetchone()
        return row is not None
    finally:
        cx.close()


def _split_sql(script: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            parts.append("\n".join(buf))
            buf = []
    if buf:
        parts.append("\n".join(buf))
    return [p.strip() for p in parts if p.strip()]
