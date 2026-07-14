"""Channel manager: seeded stations, queue top-up, next-track for liquidsoap."""
from __future__ import annotations

import json
import os
import socket
import threading
import time

import httpx

from . import config, db
from .adapters import archive, cc, library, phishin

# Sources whose channels enqueue whole shows via adapter.pick_show()/get_show().
SHOW_ADAPTERS = {"archive": archive, "phishin": phishin, "cc": cc}
STREAMABLE_SOURCES = ("archive", "phishin", "library", "cc")

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
    lic = str(show.get("licenseurl") or "")
    comm = 1 if show.get("commercial_ok", True) else 0
    db.executemany(
        "INSERT INTO queue(channel, url, title, artist, album, show_id, licenseurl, "
        "commercial_ok) VALUES(?,?,?,?,?,?,?,?)",
        [(ch["slug"], t["url"], t["title"], artist, album, show["identifier"], lic, comm)
         for t in show["tracks"]],
    )
    return len(show["tracks"])


def _enqueue_library(ch: dict) -> int:
    tracks = library.pick_tracks(ch["query"])
    if not tracks:
        return 0
    # Each top-up is its own "show" so On Demand can reconstruct it. An empty
    # show_id is FALSY, and api_show treats falsy as "nothing loaded" — which
    # would leave every library channel permanently empty in On Demand, the
    # moment there are actually files to play.
    show_id = f"library-{ch['slug']}-{int(time.time())}"
    db.executemany(
        "INSERT INTO queue(channel, url, title, artist, album, show_id) VALUES(?,?,?,?,?,?)",
        [(ch["slug"], t["url"], t["title"], t["artist"], t["album"], show_id) for t in tracks],
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
    set_nowplaying(slug, row["title"], row["artist"], row["album"], row["url"])

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

def set_nowplaying(slug: str, title: str, artist: str, album: str, url: str = "") -> None:
    """Record what's on air. The url rides along so the UI can Like the current
    track — a favourite is worthless if it can't be played back.

    Two callers race here: next_track() knows the url, but liquidsoap then POSTs
    /api/nowplaying for the same track WITHOUT one when it actually starts
    playing. Last write wins, so the POST would silently blank the url and make
    the on-air track unlikeable. Rather than depend on ordering, resolve a
    missing url from the queue row that fed this track.
    """
    if not url:
        rows = db.query(
            "SELECT url FROM queue WHERE channel=? AND title=? AND served=1 "
            "ORDER BY id DESC LIMIT 1", (slug, title))
        if rows:
            url = rows[0]["url"] or ""
    db.execute(
        "INSERT INTO nowplaying(channel, title, artist, album, url, updated_at) "
        "VALUES(?,?,?,?,?,datetime('now')) "
        "ON CONFLICT(channel) DO UPDATE SET title=excluded.title, artist=excluded.artist, "
        "album=excluded.album, url=excluded.url, updated_at=excluded.updated_at",
        (slug, title, artist, album, url))


_ICE_TTL = 2.0
_ice_cache: dict = {"at": 0.0, "mounts": {}}
_ice_lock = threading.Lock()


def _icecast_on_air() -> dict[str, str]:
    """What icecast is ACTUALLY transmitting, per mount.

    This is the only honest answer to "what's playing". The queue is NOT:
    liquidsoap PREFETCHES the next request while the current track is still on
    air, so /api/next — and the nowplaying it writes — runs a whole track ahead
    of the broadcast. icecast sets a mount's metadata when the track reaches the
    encoder, which is precisely what listeners are hearing.

    Cached briefly; the UI polls this every few seconds and icecast shouldn't wear it.
    """
    with _ice_lock:
        if time.time() - _ice_cache["at"] < _ICE_TTL:
            return _ice_cache["mounts"]
    mounts: dict[str, str] = {}
    try:
        r = httpx.get(f"{config.ICECAST_ORIGIN}/status-json.xsl", timeout=3)
        src = r.json().get("icestats", {}).get("source", [])
        src = src if isinstance(src, list) else [src]
        for s in src:
            mount = str(s.get("listenurl", "")).rsplit("/", 1)[-1]
            if mount:
                mounts[mount] = str(s.get("title") or "")
    except Exception:
        pass                                    # icecast down: fall back to the table
    with _ice_lock:
        _ice_cache.update(at=time.time(), mounts=mounts)
    return mounts


def get_nowplaying(slug: str) -> dict:
    rows = db.query("SELECT * FROM nowplaying WHERE channel=?", (slug,))
    fallback = rows[0] if rows else {
        "channel": slug, "title": "", "artist": "", "album": "", "url": ""}

    on_air = _icecast_on_air().get(slug, "")
    if not on_air:
        return fallback

    # icecast gives one flat string ("Artist - Title"), and titles can contain
    # dashes — so don't split it. Match it against the tracks we recently served
    # on this channel and take the row whose title actually appears in it. That
    # gives back the structured record (artist, album, url) the UI needs, and the
    # url is what makes the on-air track Likeable.
    recent = db.query(
        "SELECT title, artist, album, url FROM queue WHERE channel=? AND served=1 "
        "ORDER BY id DESC LIMIT 12", (slug,))
    for row in recent:
        t = (row["title"] or "").strip()
        if t and t.lower() in on_air.lower():
            return {"channel": slug, "title": t, "artist": row["artist"],
                    "album": row["album"], "url": row["url"] or ""}
    return fallback


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
    """Skip the current track via liquidsoap's telnet server.

    Commands are named after the sources in radio.liq. The icecast *output*
    (`out_<slug>`) owns the playing track, so `out_<slug>.skip` is the one that
    actually drops it. There is no `<slug>.skip` — the request.dynamic queue only
    offers `<slug>.flush_and_skip`, which also throws away everything prefetched,
    so it's a last resort.

    Liquidsoap answers "Done!" or "ERROR ...". A connected socket is NOT proof of
    a skip: sending a command that doesn't exist still connects and still sends,
    which is how this used to report success while the track played on.
    """
    for cmd in (f"out_{slug}.skip", f"{slug}.flush_and_skip"):
        try:
            with socket.create_connection(
                    (config.LIQUIDSOAP_HOST, config.LIQUIDSOAP_TELNET_PORT), timeout=3) as s:
                s.sendall(f"{cmd}\nquit\n".encode())
                reply = s.recv(4096).decode(errors="replace")
        except OSError:
            continue
        if "ERROR" not in reply.upper():
            return True
    return False
