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
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,             -- owner-set station state: 'banner' etc
  value TEXT DEFAULT '',
  updated_at TEXT DEFAULT ({_NOW})
);
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

-- ── auth. Email is the identity: no usernames, no passwords, no OAuth. ───────
-- Tokens and codes are stored HASHED: a database leak must not be a pile of
-- working logins. Sessions are server-side because the whole point is revocation.
CREATE TABLE IF NOT EXISTS members(
  email TEXT PRIMARY KEY,             -- lowercased. THE identity.
  name TEXT DEFAULT '',
  role TEXT DEFAULT 'member',         -- owner | member
  status TEXT DEFAULT 'pending',      -- pending | approved | revoked
  note TEXT DEFAULT '',               -- "I'm your cousin Bob"
  created_at TEXT DEFAULT ({_NOW}),
  approved_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS invites(
  token_hash TEXT PRIMARY KEY,
  label TEXT DEFAULT '',
  created_at TEXT DEFAULT ({_NOW}),
  revoked_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS approvals(
  token_hash TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS login_attempts(
  id SERIAL PRIMARY KEY,
  email TEXT NOT NULL,
  token_hash TEXT NOT NULL,           -- the magic link
  code_hash TEXT NOT NULL,            -- the typeable code (any device)
  expires_at TEXT NOT NULL,
  used_at TEXT DEFAULT '',
  attempts INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_login_email ON login_attempts(email, id);
CREATE TABLE IF NOT EXISTS sessions(
  id_hash TEXT PRIMARY KEY,
  email TEXT NOT NULL,
  created_at TEXT DEFAULT ({_NOW}),
  expires_at TEXT NOT NULL,
  last_seen TEXT DEFAULT '',
  user_agent TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_email ON sessions(email);
-- ── access keys. The DEAD-SIMPLE path (2026-07-14): the owner hands a person a personal
-- link AND a code (same credential, two forms). Tap the link or type the code -> you're in,
-- forever (the session slides). REUSABLE, not single-use like login_attempts: a family member
-- taps their link whenever they get a new phone. Recovery = the owner rotates (new pair) or
-- revokes. Stored hashed, like everything else. No email required to hold one.
CREATE TABLE IF NOT EXISTS access_keys(
  token_hash TEXT PRIMARY KEY,       -- the /k/<token> link
  code_hash TEXT NOT NULL,           -- the typeable code, same grant
  email TEXT NOT NULL,               -- the member (internal id) it authenticates
  created_at TEXT DEFAULT ({_NOW}),
  revoked_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_access_email ON access_keys(email);
CREATE TABLE IF NOT EXISTS favourites(
  email TEXT NOT NULL,
  url TEXT NOT NULL,                  -- a favourite is worthless if you can't play it back
  title TEXT DEFAULT '',
  artist TEXT DEFAULT '',
  album TEXT DEFAULT '',
  channel TEXT DEFAULT '',
  added_at TEXT DEFAULT ({_NOW}),
  PRIMARY KEY (email, url)
);
-- ── spots. A photo of music you heard in the wild -> Claude reads it -> matched to your crate
-- or saved to a wishlist. The photo lives in the music volume (.spots/), served members-only.
CREATE TABLE IF NOT EXISTS spots(
  id SERIAL PRIMARY KEY,
  email TEXT DEFAULT '',              -- who spotted it
  image_path TEXT DEFAULT '',        -- /music/.spots/<id>.jpg (the snapshot)
  status TEXT DEFAULT 'unknown',     -- matched | wishlist | unknown
  artist TEXT DEFAULT '',
  title TEXT DEFAULT '',
  album TEXT DEFAULT '',
  year TEXT DEFAULT '',
  confidence TEXT DEFAULT '',        -- high | medium | low
  saw TEXT DEFAULT '',               -- what the AI saw ("car stereo display")
  mbid TEXT DEFAULT '',
  cover_url TEXT DEFAULT '',         -- real sleeve fetched for a wishlist hit
  matched_dir TEXT DEFAULT '',       -- catalog folder, if you own it
  matched_url TEXT DEFAULT '',       -- playable track url, if pinned
  links TEXT DEFAULT '{{}}',         -- json: youtube / discogs / musicbrainz
  created_at TEXT DEFAULT ({_NOW})
);
CREATE INDEX IF NOT EXISTS idx_spots_id ON spots(id DESC);

-- ── contributions: a member's uploaded folder, and what station it became.
-- Written by jam-contribd (host daemon) the moment it accepts an upload. The
-- member's identity comes from Tailscale (tailscale whois the connecting IP),
-- not from a password or key, so there is deliberately no separate auth token
-- here — this row is simply the record of "who sent this," for the personal-
-- radio "contributed slice" (see docs/DESIGN-contributor-identity.md).
CREATE TABLE IF NOT EXISTS contributions(
  id SERIAL PRIMARY KEY,
  email TEXT NOT NULL,               -- the contributor (member) — matches members.email
  slug TEXT NOT NULL,                -- the channel it became (may not exist yet at insert time)
  folder_name TEXT DEFAULT '',       -- what they named it (also the station's display name)
  created_at TEXT DEFAULT ({_NOW})
);
CREATE INDEX IF NOT EXISTS idx_contributions_email ON contributions(email);
"""

# Additive, idempotent, safe to re-run. Postgres does ADD COLUMN IF NOT EXISTS natively, so
# these don't need the try/except the SQLite version did.
MIGRATIONS = (
    "ALTER TABLE nowplaying ADD COLUMN IF NOT EXISTS url TEXT DEFAULT ''",
    "ALTER TABLE queue ADD COLUMN IF NOT EXISTS licenseurl TEXT DEFAULT ''",
    "ALTER TABLE queue ADD COLUMN IF NOT EXISTS commercial_ok INTEGER DEFAULT 1",
    # a key-link member has no email — 'contact' is the owner's own note on how to reach them
    "ALTER TABLE members ADD COLUMN IF NOT EXISTS contact TEXT DEFAULT ''",
    # a passphrase anyone can set to sign in with (email + passphrase). PBKDF2, salted per-user
    # — a real password hash, not the light token hash. Empty = no passphrase set.
    "ALTER TABLE members ADD COLUMN IF NOT EXISTS pass_hash TEXT DEFAULT ''",
    "ALTER TABLE members ADD COLUMN IF NOT EXISTS pass_salt TEXT DEFAULT ''",
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
