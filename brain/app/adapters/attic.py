"""Source adapter for a shelf server — vault music served over HTTP by attic-server.py.

The remote-URL pattern (like archive.py), not the local-disk one (library.py): the
music lives behind a tiny HTTP contract (/catalog.json + /file/<root>/<path>) served
from the mini HOST, because only the host can see the AFP-mounted Time Capsule. The
contract is the extension point — any machine that speaks it can feed stations
(dad's Mac over the tailnet, someday).

Track urls are stored SAME-ORIGIN ("/attic/<root>/<path>") like library's "/music/..."
urls: the browser plays them through the brain's members-gated proxy (mixes, on-demand,
EQ), and channels._for_liquidsoap() turns them absolute+keyed for the radio container.
The browser can't reach host.docker.internal, so absolute shelf-server urls would be
radio-only — the proxy makes one url work everywhere.
"""
from __future__ import annotations

import logging
import random
import time

import httpx

from .. import config

log = logging.getLogger("jam.attic")

CATALOG_TTL = 300.0     # list_channels probes playability often; don't wear the host server
NEG_TTL = 60.0          # unreachable: retry soon, but a flap can't hammer or thrash the dial

_client: httpx.Client | None = None
_cache: dict = {"at": 0.0, "ttl": 0.0, "catalog": None}


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=15)
    return _client


def set_client(c: httpx.Client | None) -> None:
    """Test hook: inject a client with a MockTransport (and start from a cold cache)."""
    global _client
    _client = c
    _cache.update(at=0.0, ttl=0.0, catalog=None)


def _catalog() -> dict:
    if not config.ATTIC_SERVER_URL:
        return {"categories": [], "tracks": []}
    now = time.time()
    if _cache["catalog"] is not None and now - _cache["at"] < _cache["ttl"]:
        return _cache["catalog"]
    try:
        r = client().get(f"{config.ATTIC_SERVER_URL}/catalog.json")
        r.raise_for_status()
        cat = r.json()
        _cache.update(at=now, ttl=CATALOG_TTL, catalog=cat)
    except Exception as e:
        log.warning("attic catalog unreachable (%s) — vault stations off air", e)
        cat = {"categories": [], "tracks": []}
        _cache.update(at=now, ttl=NEG_TTL, catalog=cat)
    return cat


def _track(entry: dict) -> dict:
    # "/file/<root>/<path>" (the server's url) -> "/attic/<root>/<path>" (the brain's proxy)
    t = {
        "url": "/attic/" + entry["url"][len("/file/"):],
        "title": entry.get("title", ""),
        "artist": entry.get("artist", ""),
        "album": entry.get("album", ""),
    }
    if t["artist"] and t["album"]:
        # art is fetched lazily the first time a client looks (see /api/attic/cover) —
        # 16k tracks will never be hand-curated, and don't need to be
        from urllib.parse import urlencode
        t["cover_url"] = "/api/attic/cover?" + urlencode(
            {"artist": t["artist"], "album": t["album"]})
    return t


def _filtered(cfg: dict) -> list[dict]:
    tracks = _catalog().get("tracks") or []
    if cfg.get("artist"):
        want = cfg["artist"].strip().lower()
        return [t for t in tracks if (t.get("artist") or "").lower() == want]
    if cfg.get("letter"):
        want = cfg["letter"].strip().lower()[:1]
        return [t for t in tracks if (t.get("artist") or "").lower().startswith(want)]
    if cfg.get("genre"):
        want = cfg["genre"].strip().lower()
        return [t for t in tracks if any((g or "").lower() == want
                                         for g in t.get("genres") or [])]
    if cfg.get("spotlight"):
        artists = sorted({t.get("artist", "") for t in tracks if t.get("artist")})
        if not artists:
            return []
        pick = random.choice(artists)
        return [t for t in tracks if t.get("artist") == pick]
    return tracks                                    # {"all": true} — The Vault


def pick_tracks(cfg: dict, count: int = 25) -> list[dict]:
    pool = _filtered(cfg)
    if not pool:
        return []
    picks = random.sample(pool, min(count, len(pool)))
    out = [_track(t) for t in picks]
    log.info("attic pick_tracks: query=%s pool=%d picked=%d artists=%d",
             cfg, len(pool), len(out), len({t["artist"] for t in out}))
    return out


def build_mix(genre: str, count: int = 30) -> list[dict]:
    """A shuffled tracklist across a vault category — twin of library.build_mix,
    show-shaped by the caller so every client plays it through machinery it has."""
    tracks = [_track(t) for t in _filtered({"genre": genre})]
    random.shuffle(tracks)
    return tracks[:max(1, min(count, 100))]


def categories() -> list[str]:
    """The sections this shelf server declared it wants as channels."""
    return list(_catalog().get("categories") or [])


def genre_counts() -> dict[str, int]:
    """Track counts per DECLARED category — the input to channels.sync_attic_channels."""
    tracks = _catalog().get("tracks") or []
    out = {}
    for name in categories():
        want = name.lower()
        out[name] = sum(1 for t in tracks
                        if any((g or "").lower() == want for g in t.get("genres") or []))
    return out
