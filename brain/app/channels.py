"""Channel manager: seeded stations, queue top-up, next-track for liquidsoap."""
from __future__ import annotations

import json
import os
import socket
import threading

import httpx

from . import config, db
from .adapters import archive, library, phishin

# Sources whose channels enqueue whole shows via adapter.pick_show()/get_show().
SHOW_ADAPTERS = {"archive": archive, "phishin": phishin}
STREAMABLE_SOURCES = ("archive", "phishin", "library")

SEED_CHANNELS = [
    {
        "slug": "dead77",
        "name": "Dead '77",
        "description": "Grateful Dead 1977 — the year everyone argues about, best-rated tapes first.",
        "source": "archive",
        "query": {"collections": ["GratefulDead"], "year": 1977, "min_rating": 4.2},
    },
    {
        "slug": "jam",
        "name": "Jam Bands Live",
        "description": "Umphrey's, moe., Biscuits, Cheese, Panic, Goose — well-rated live tapes.",
        "source": "archive",
        "query": {
            "collections": ["UmphreysMcGee", "moe", "DiscoBiscuits",
                            "StringCheeseIncident", "WidespreadPanic", "Goose"],
            "min_rating": 4.0,
        },
    },
    {
        "slug": "phish",
        "name": "Phish",
        "description": "Phish from phish.in — the most-liked tapes across every era.",
        "source": "phishin",
        "query": {"sort": "likes_count:desc", "rows": 100},
    },
    {
        "slug": "fusion",
        "name": "70s Fusion",
        "description": "Your own fusion library (drop files in music/fusion/).",
        "source": "library",
        "query": {"folders": ["fusion"]},
    },
    {
        "slug": "latenight-jazz",
        "name": "Late Night Jazz",
        "description": "Jam-jazz from the Archive: MMW, Jacob Fred, Garaj Mahal.",
        "source": "archive",
        "query": {
            "collections": ["MedeskiMartinandWood", "JacobFredJazzOdyssey", "GarajMahal"],
            "min_rating": 3.5,
        },
    },
]

_topup_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(slug: str) -> threading.Lock:
    with _locks_guard:
        return _topup_locks.setdefault(slug, threading.Lock())


def ensure_seeded() -> None:
    for ch in SEED_CHANNELS:
        db.execute(
            "INSERT OR IGNORE INTO channels(slug, name, description, source, query) "
            "VALUES(?,?,?,?,?)",
            (ch["slug"], ch["name"], ch["description"], ch["source"],
             json.dumps(ch["query"])),
        )


def list_channels(streamable_only: bool = False) -> list[dict]:
    rows = db.query("SELECT * FROM channels WHERE enabled=1 ORDER BY created_at")
    out = []
    for r in rows:
        r["query"] = json.loads(r.get("query") or "{}")
        # A library channel is only real if the files are actually on disk —
        # otherwise it mounts and broadcasts silence. Surface that as `playable`
        # so the UI can say so, and keep it out of liquidsoap's mount list.
        r["playable"] = (r["source"] != "library"
                         or bool(library.pick_tracks(r["query"], count=1)))
        if streamable_only and (r["source"] not in STREAMABLE_SOURCES or not r["playable"]):
            continue
        out.append(r)
    return out


def get_channel(slug: str) -> dict | None:
    rows = db.query("SELECT * FROM channels WHERE slug=?", (slug,))
    if not rows:
        return None
    ch = rows[0]
    ch["query"] = json.loads(ch.get("query") or "{}")
    return ch


def create_channel(slug: str, name: str, description: str, source: str, query: dict) -> dict:
    if source not in STREAMABLE_SOURCES:
        raise ValueError(f"source must be one of {', '.join(STREAMABLE_SOURCES)}")
    db.execute(
        "INSERT OR REPLACE INTO channels(slug, name, description, source, query) "
        "VALUES(?,?,?,?,?)",
        (slug, name, description, source, json.dumps(query)),
    )
    return get_channel(slug)  # type: ignore[return-value]


def _recent_show_ids(slug: str) -> set[str]:
    rows = db.query(
        "SELECT show_id FROM history WHERE channel=? ORDER BY id DESC LIMIT 300", (slug,))
    rows += db.query("SELECT show_id FROM queue WHERE channel=?", (slug,))
    return {r["show_id"] for r in rows if r.get("show_id")}


def _enqueue_show_channel(ch: dict, adapter) -> int:
    show = adapter.pick_show(ch["query"], _recent_show_ids(ch["slug"]))
    if not show or not show["tracks"]:
        return 0
    album = f"{show['title']}"
    artist = str(show.get("creator") or "")
    db.executemany(
        "INSERT INTO queue(channel, url, title, artist, album, show_id) VALUES(?,?,?,?,?,?)",
        [(ch["slug"], t["url"], t["title"], artist, album, show["identifier"])
         for t in show["tracks"]],
    )
    return len(show["tracks"])


def _enqueue_library(ch: dict) -> int:
    tracks = library.pick_tracks(ch["query"])
    if not tracks:
        return 0
    db.executemany(
        "INSERT INTO queue(channel, url, title, artist, album, show_id) VALUES(?,?,?,?,?,?)",
        [(ch["slug"], t["url"], t["title"], t["artist"], t["album"], "") for t in tracks],
    )
    return len(tracks)


def ensure_queue(slug: str) -> int:
    """Top up a channel if it's running low. Returns number of tracks added."""
    ch = get_channel(slug)
    if not ch:
        return 0
    lock = _lock_for(slug)
    if not lock.acquire(blocking=False):
        return 0  # a top-up is already in flight
    try:
        unserved = db.query(
            "SELECT COUNT(*) AS n FROM queue WHERE channel=? AND served=0", (slug,))[0]["n"]
        if unserved >= config.MIN_QUEUE:
            return 0
        if ch["source"] in SHOW_ADAPTERS:
            return _enqueue_show_channel(ch, SHOW_ADAPTERS[ch["source"]])
        if ch["source"] == "library":
            return _enqueue_library(ch)
        return 0
    finally:
        lock.release()


# ---------------------------------------------------------------- prefetch

def prefetch(slug: str, count: int = 3) -> None:
    """Download the next few remote tracks into the shared cache volume."""
    if not config.PREFETCH:
        return
    rows = db.query(
        "SELECT * FROM queue WHERE channel=? AND served=0 AND local_path IS NULL "
        "AND url LIKE 'http%' ORDER BY id LIMIT ?", (slug, count))
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    for row in rows:
        dest = os.path.join(config.CACHE_DIR, f"{slug}-{row['id']}.mp3")
        try:
            with httpx.stream("GET", row["url"], timeout=60, follow_redirects=True) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        f.write(chunk)
            db.execute("UPDATE queue SET local_path=? WHERE id=?", (dest, row["id"]))
        except Exception:
            try:
                os.unlink(dest)
            except OSError:
                pass


def _cleanup_cache(slug: str, keep_last: int = 2) -> None:
    rows = db.query(
        "SELECT id, local_path FROM queue WHERE channel=? AND served=1 "
        "AND local_path IS NOT NULL ORDER BY id DESC", (slug,))
    for row in rows[keep_last:]:
        try:
            if row["local_path"] and os.path.exists(row["local_path"]):
                os.unlink(row["local_path"])
        except OSError:
            pass
        db.execute("UPDATE queue SET local_path=NULL WHERE id=?", (row["id"],))


# ---------------------------------------------------------------- next track

def _annotate(row: dict) -> str:
    def esc(s: str) -> str:
        return str(s or "").replace("\\", "").replace('"', "'")
    src = row["url"]
    if row.get("local_path") and os.path.exists(row["local_path"]):
        src = row["local_path"]
    return (f'annotate:title="{esc(row["title"])}",artist="{esc(row["artist"])}",'
            f'album="{esc(row["album"])}":{src}')


def next_track(slug: str) -> str:
    """Called by liquidsoap. Returns an annotate: URI, or '' if nothing queued."""
    rows = db.query(
        "SELECT * FROM queue WHERE channel=? AND served=0 ORDER BY id LIMIT 1", (slug,))
    if not rows:
        added = ensure_queue(slug)
        if added:
            prefetch(slug, count=1)  # grab at least the first one synchronously
        rows = db.query(
            "SELECT * FROM queue WHERE channel=? AND served=0 ORDER BY id LIMIT 1", (slug,))
        if not rows:
            return ""
    row = rows[0]
    db.execute("UPDATE queue SET served=1 WHERE id=?", (row["id"],))
    db.execute(
        "INSERT INTO history(channel, title, artist, album, show_id) VALUES(?,?,?,?,?)",
        (slug, row["title"], row["artist"], row["album"], row["show_id"]))
    set_nowplaying(slug, row["title"], row["artist"], row["album"])

    def background() -> None:
        try:
            ensure_queue(slug)
            prefetch(slug)
            _cleanup_cache(slug)
        except Exception:
            pass

    threading.Thread(target=background, daemon=True).start()
    return _annotate(row)


# ---------------------------------------------------------------- now playing

def set_nowplaying(slug: str, title: str, artist: str, album: str) -> None:
    db.execute(
        "INSERT INTO nowplaying(channel, title, artist, album, updated_at) "
        "VALUES(?,?,?,?,datetime('now')) "
        "ON CONFLICT(channel) DO UPDATE SET title=excluded.title, artist=excluded.artist, "
        "album=excluded.album, updated_at=excluded.updated_at",
        (slug, title, artist, album))


def get_nowplaying(slug: str) -> dict:
    rows = db.query("SELECT * FROM nowplaying WHERE channel=?", (slug,))
    return rows[0] if rows else {"channel": slug, "title": "", "artist": "", "album": ""}


def queue_status(slug: str) -> dict:
    upcoming = db.query(
        "SELECT title, artist, album FROM queue WHERE channel=? AND served=0 "
        "ORDER BY id LIMIT 15", (slug,))
    n = db.query("SELECT COUNT(*) AS n FROM queue WHERE channel=? AND served=0", (slug,))[0]["n"]
    return {"channel": slug, "unserved": n, "upcoming": upcoming,
            "nowplaying": get_nowplaying(slug)}


def clear_queue(slug: str) -> int:
    rows = db.query(
        "SELECT local_path FROM queue WHERE channel=? AND served=0 "
        "AND local_path IS NOT NULL", (slug,))
    for row in rows:  # don't orphan prefetched files in the cache volume
        try:
            os.unlink(row["local_path"])
        except OSError:
            pass
    return db.execute("DELETE FROM queue WHERE channel=? AND served=0", (slug,))


def enqueue_show(slug: str, identifier: str, clear: bool = False) -> int:
    """Queue a specific show on a channel (DJ tool).

    The channel's source picks the adapter: archive identifiers for archive
    channels, YYYY-MM-DD dates for phishin channels.
    """
    ch = get_channel(slug)
    adapter = SHOW_ADAPTERS.get((ch or {}).get("source", ""), archive)
    if clear:
        clear_queue(slug)
    show = adapter.get_show(identifier)
    if not show["tracks"]:
        return 0
    db.executemany(
        "INSERT INTO queue(channel, url, title, artist, album, show_id) VALUES(?,?,?,?,?,?)",
        [(slug, t["url"], t["title"], str(show.get("creator") or ""), show["title"],
          show["identifier"]) for t in show["tracks"]],
    )
    return len(show["tracks"])


# ---------------------------------------------------------------- skip

def skip(slug: str) -> bool:
    """Best-effort skip via liquidsoap's telnet server."""
    for cmd in (f"{slug}.skip", f"out_{slug}.skip"):
        try:
            with socket.create_connection(
                    (config.LIQUIDSOAP_HOST, config.LIQUIDSOAP_TELNET_PORT), timeout=3) as s:
                s.sendall(f"{cmd}\nquit\n".encode())
                s.recv(1024)
            return True
        except OSError:
            continue
    return False
