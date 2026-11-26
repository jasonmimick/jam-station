"""Who's on the air, right now.

Two sources of truth, merged:

- RADIO: every radio listener holds an open /stream/<slug> connection through the brain,
  and that request carries their session cookie. Register on connect, unregister when the
  socket dies. No polling, no client code — the connection IS the presence.
- ON DEMAND: the browser pulls Archive MP3s directly (never through us), so the UI sends a
  small heartbeat while playing. A heartbeat counts as presence for HEARTBEAT_TTL seconds.

In-memory on purpose: presence is ephemeral, the brain is one process, and losing it on a
restart just means an empty room for a minute. Don't move this to Postgres.
"""
from __future__ import annotations

import itertools
import threading
import time

HEARTBEAT_TTL = 75          # ~2.5 missed 30s beats = they're gone
SEEN_TTL = 90               # an app that hasn't spoken for this long has left the room

_lock = threading.Lock()
_streams: dict[int, dict] = {}     # open /stream connections
_beats: dict[str, dict] = {}       # on-demand heartbeats, keyed by member email or anon id
_seen: dict[tuple, dict] = {}      # (email, client) -> presence of an OPEN app/page
_ids = itertools.count(1)


def stream_connect(name: str, email: str, channel: str, client: str = "") -> int:
    sid = next(_ids)
    with _lock:
        _streams[sid] = {"name": name or "Someone", "email": email or "",
                         "channel": channel, "mode": "radio", "since": time.time(),
                         "client": client}
    return sid


def stream_disconnect(sid: int) -> None:
    with _lock:
        e = _streams.pop(sid, None)
    if e:   # the session is over — log it for usage reports (outside the lock: it's a DB write)
        _ended(e, time.time())


def _ended(e: dict, end: float) -> None:
    from . import usage   # lazy: presence stays importable without the DB layer
    usage.record(e["channel"], e["mode"], e["email"], e.get("client", ""), e["since"],
                 end - e["since"])


def _expire_beats(now: float) -> list[dict]:
    """Pop expired heartbeats. Caller holds _lock; caller logs the returned ones after."""
    gone = [k for k, b in _beats.items() if b["until"] < now]
    return [_beats.pop(k) for k in gone]


def heartbeat(name: str, email: str, key: str, channel: str, client: str = "") -> None:
    now = time.time()
    ended = []
    with _lock:
        ended = _expire_beats(now)
        prev = _beats.get(key)
        if prev and prev["channel"] != channel:
            ended.append(prev)          # moved to another channel: that session is over
        since = prev["since"] if prev and prev["channel"] == channel else now
        _beats[key] = {"name": name or "Someone", "email": email or "", "channel": channel,
                       "mode": "ondemand", "since": since, "last": now,
                       "until": now + HEARTBEAT_TTL, "client": client}
    for b in ended:
        _ended(b, b.get("last", b["since"]))


def seen(email: str, name: str, client: str) -> None:
    """A signed-in request happened — that person's client is IN THE ROOM, whether or not
    audio is playing. Keyed per (member, client) so the Mac app, the iOS app, and a browser
    each count as their own session. (Two devices on the same client string collapse — the
    apps don't send a device id; good enough until they do.)"""
    key = (email, client)
    with _lock:
        prev = _seen.get(key)
        _seen[key] = {"name": name or "Someone", "email": email, "client": client,
                      "since": prev["since"] if prev else time.time(),
                      "until": time.time() + SEEN_TTL}


def sweep() -> None:
    """Log on-demand sessions whose heartbeats stopped. listeners() and heartbeat() do this
    too; the usage report calls it so a quiet house still gets its last session counted."""
    with _lock:
        ended = _expire_beats(time.time())
    for b in ended:
        _ended(b, b.get("last", b["since"]))


def online() -> list[dict]:
    """Who has an app or page open right now."""
    now = time.time()
    with _lock:
        for k in [k for k, e in _seen.items() if e["until"] < now]:
            del _seen[k]
        rows = sorted(_seen.values(), key=lambda e: e["since"])
    return [{"name": e["name"], "client": e["client"], "for_seconds": int(now - e["since"])}
            for e in rows]


def listeners() -> list[dict]:
    """Everyone here now, one row per (person, channel). A member with the same channel
    open twice (two tabs, radio + a stale beat) collapses to one row — radio wins."""
    now = time.time()
    rows: dict[tuple, dict] = {}
    with _lock:
        ended = _expire_beats(now)
        for src in (list(_beats.values()), list(_streams.values())):   # streams last: radio wins
            for e in src:
                key = (e["email"] or e["name"], e["channel"])
                rows[key] = e
    for b in ended:
        _ended(b, b.get("last", b["since"]))
    return [{"name": e["name"], "channel": e["channel"], "mode": e["mode"],
             "for_seconds": int(now - e["since"])}
            for e in sorted(rows.values(), key=lambda e: e["since"])]
