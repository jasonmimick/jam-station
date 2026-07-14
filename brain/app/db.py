import os
import sqlite3
import threading

from . import config

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels(
  slug TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  source TEXT NOT NULL,             -- archive | library | stream
  query TEXT DEFAULT '{}',          -- JSON config for the source adapter
  enabled INTEGER DEFAULT 1,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS queue(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT NOT NULL,
  url TEXT NOT NULL,
  local_path TEXT,
  title TEXT DEFAULT '',
  artist TEXT DEFAULT '',
  album TEXT DEFAULT '',
  show_id TEXT DEFAULT '',
  served INTEGER DEFAULT 0,
  added_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_queue_channel ON queue(channel, served, id);
CREATE TABLE IF NOT EXISTS history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT NOT NULL,
  title TEXT DEFAULT '',
  artist TEXT DEFAULT '',
  album TEXT DEFAULT '',
  show_id TEXT DEFAULT '',
  played_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS nowplaying(
  channel TEXT PRIMARY KEY,
  title TEXT DEFAULT '',
  artist TEXT DEFAULT '',
  album TEXT DEFAULT '',
  url TEXT DEFAULT '',
  updated_at TEXT DEFAULT (datetime('now'))
);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(config.DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init() -> None:
    with _lock, _connect() as con:
        con.executescript(SCHEMA)
        # CREATE TABLE IF NOT EXISTS won't add a column to a table that already
        # exists, and the live stations have been running for a while. Additive
        # migrations go here — each one idempotent, each one safe to re-run.
        for stmt in (
            "ALTER TABLE nowplaying ADD COLUMN url TEXT DEFAULT ''",
            # ~25% of Creative Commons audio is NonCommercial-only. Record the licence on
            # every track NOW, so the day there's a paid tier, filtering it out is a WHERE
            # clause instead of re-crawling the whole catalogue.
            "ALTER TABLE queue ADD COLUMN licenseurl TEXT DEFAULT ''",
            "ALTER TABLE queue ADD COLUMN commercial_ok INTEGER DEFAULT 1",
        ):
            try:
                con.execute(stmt)
            except sqlite3.OperationalError:
                pass          # already applied


def query(sql: str, params: tuple = ()) -> list[dict]:
    with _lock, _connect() as con:
        rows = con.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def execute(sql: str, params: tuple = ()) -> int:
    with _lock, _connect() as con:
        cur = con.execute(sql, params)
        con.commit()
        return cur.lastrowid or cur.rowcount


def executemany(sql: str, seq: list[tuple]) -> None:
    with _lock, _connect() as con:
        con.executemany(sql, seq)
        con.commit()
