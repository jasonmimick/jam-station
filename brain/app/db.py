"""Postgres, via slab.

WHY WE MOVED OFF SQLITE (2026-07-13, before auth):

SQLite-on-a-volume was genuinely fine for a radio: one writer, one node, and if the play
log vanished you'd shrug. It stops being fine the moment there are MEMBERS AND SESSIONS —
lose that table and every person in the family is locked out, permanently. Different risk
class entirely, and it needs backups and a real migration story.

We did it NOW because now was the cheapest it would ever be: the stations had just moved
into code (they reseed themselves), the queue regenerates from the adapters in seconds, and
nowplaying is rewritten every track. Only the play history was real data, and that copies
across. After auth ships there are live sessions and it becomes a careful migration with
downtime. This was a Tuesday.

TWO DELIBERATE CHOICES:

1. `query`/`execute`/`executemany` translate `?` -> `%s`, so the ~67 placeholders across the
   app did not have to change. This facade was already doing its job; we kept it.

2. Timestamps stay TEXT in the exact format SQLite produced ('YYYY-MM-DD HH:MM:SS', UTC),
   NOT timestamptz. The frontend parses them by hand (`ts.replace(" ","T") + "Z"`), and the
   API returns them as-is. Switching to a real timestamp type would change the JSON and
   silently break every "3m ago" in the UI. A migration should move the storage, not the
   contract.
"""
from __future__ import annotations

import re

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

# SQLite's datetime('now') is UTC, space-separated, second resolution. Reproduce it exactly.
_NOW = "to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI:SS')"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS channels(
  slug TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  source TEXT NOT NULL,             -- archive | phishin | library | cc
  query TEXT DEFAULT '{{}}',        -- JSON config for the source adapter
  enabled INTEGER DEFAULT 1,
  created_at TEXT DEFAULT ({_NOW})
);
CREATE TABLE IF NOT EXISTS queue(
  id SERIAL PRIMARY KEY,
  channel TEXT NOT NULL,
  url TEXT NOT NULL,
  local_path TEXT,
  title TEXT DEFAULT '',
  artist TEXT DEFAULT '',
  album TEXT DEFAULT '',
  show_id TEXT DEFAULT '',
  served INTEGER DEFAULT 0,
  licenseurl TEXT DEFAULT '',
  commercial_ok INTEGER DEFAULT 1,
  added_at TEXT DEFAULT ({_NOW})
);
CREATE INDEX IF NOT EXISTS idx_queue_channel ON queue(channel, served, id);
CREATE TABLE IF NOT EXISTS history(
  id SERIAL PRIMARY KEY,
  channel TEXT NOT NULL,
  title TEXT DEFAULT '',
  artist TEXT DEFAULT '',
  album TEXT DEFAULT '',
  show_id TEXT DEFAULT '',
  played_at TEXT DEFAULT ({_NOW})
);
CREATE INDEX IF NOT EXISTS idx_history_channel ON history(channel, id);
CREATE TABLE IF NOT EXISTS nowplaying(
  channel TEXT PRIMARY KEY,
  title TEXT DEFAULT '',
  artist TEXT DEFAULT '',
  album TEXT DEFAULT '',
  url TEXT DEFAULT '',
  updated_at TEXT DEFAULT ({_NOW})
);
"""

# Additive, idempotent, safe to re-run. Postgres does ADD COLUMN IF NOT EXISTS natively, so
# these don't need the try/except the SQLite version did.
MIGRATIONS = (
    "ALTER TABLE nowplaying ADD COLUMN IF NOT EXISTS url TEXT DEFAULT ''",
    "ALTER TABLE queue ADD COLUMN IF NOT EXISTS licenseurl TEXT DEFAULT ''",
    "ALTER TABLE queue ADD COLUMN IF NOT EXISTS commercial_ok INTEGER DEFAULT 1",
)

_pool: ConnectionPool | None = None
_QMARK = re.compile(r"\?")


def _sql(sql: str) -> str:
    """`?` -> `%s`. The app speaks sqlite's placeholder; the driver speaks postgres's."""
    return _QMARK.sub("%s", sql)


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=8,
                               kwargs={"row_factory": dict_row}, open=True)
    return _pool


def init() -> None:
    with pool().connection() as con:
        for stmt in filter(None, (s.strip() for s in SCHEMA.split(";"))):
            con.execute(stmt)
        for stmt in MIGRATIONS:
            con.execute(stmt)


def query(sql: str, params: tuple = ()) -> list[dict]:
    with pool().connection() as con:
        return con.execute(_sql(sql), params).fetchall()


def execute(sql: str, params: tuple = ()) -> int:
    with pool().connection() as con:
        cur = con.execute(_sql(sql), params)
        return cur.rowcount


def executemany(sql: str, seq: list[tuple]) -> None:
    if not seq:
        return
    with pool().connection() as con:
        con.cursor().executemany(_sql(sql), seq)
