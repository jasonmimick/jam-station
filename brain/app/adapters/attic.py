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
        old = _cache["catalog"]
        if old and old.get("tracks"):
            # a fetch hiccup must not blank a working dial — serve the last-known
            # catalog and try again after the negative TTL
            log.warning("attic catalog fetch failed (%s) — serving stale", e)
            _cache.update(at=now, ttl=NEG_TTL)
            return old
        log.warning("attic catalog unreachable (%s) — vault stations off air", e)
        cat = {"categories": [], "tracks": []}
        # no data yet (typically boot): retry quickly rather than sitting empty for a minute
        _cache.update(at=now, ttl=5.0, catalog=cat)
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


def list_albums() -> list[dict]:
    """The attic crate: one entry per album folder in the vault catalog — the browse
    view of "what's in the attic". NO cover_url here, deliberately: the grid renders
    hundreds of tiles at once and every cover is a lazy iTunes fetch — the UI's
    generated placard carries the grid, and the real sleeve loads when an album is
    opened or played (per-track cover_url)."""
    seen: dict = {}
    for t in _catalog().get("tracks") or []:
        d = t["path"].rsplit("/", 1)[0] if "/" in t["path"] else ""
        e = seen.get((t["root"], d))
        if e is None:
            seen[(t["root"], d)] = e = {
                "dir": f"attic:{t['root']}/{d}",
                "artist": t.get("artist", ""),
                "album": t.get("album", "") or "Loose Tracks",
                "tracks": 0, "mtime": 0, "src": "attic",
            }
        e["tracks"] += 1
    out = list(seen.values())
    out.sort(key=lambda a: ((a["artist"] or "").lower(), (a["album"] or "").lower()))
    return out


def album_tracks(dir_key: str) -> list[dict]:
    """One attic album as an ordered tracklist (filenames carry the running order).
    `dir_key` is "attic:<root>/<folder path>" straight from list_albums."""
    if not dir_key.startswith("attic:"):
        return []
    root, _, d = dir_key[len("attic:"):].partition("/")
    ts = [t for t in _catalog().get("tracks") or []
          if t["root"] == root
          and (t["path"].rsplit("/", 1)[0] if "/" in t["path"] else "") == d]
    ts.sort(key=lambda t: t["path"])
    return [_track(t) for t in ts]


def artist_mix(name: str, count: int = 60) -> list[dict]:
    """Everything by one artist, shuffled — 'play that artist' from a track you liked.
    Show-shaped by the caller, same as build_mix."""
    tracks = [_track(t) for t in _filtered({"artist": name})]
    random.shuffle(tracks)
    return tracks[:max(1, min(count, 200))]


def stats() -> dict:
    """How much music we have — the headline numbers for the crate and anywhere
    else that wants to brag. Bytes come from the shelf server's walk; the rest
    derives from the catalog."""
    cat = _catalog()
    tracks = cat.get("tracks") or []
    albums = {(t["root"], t["path"].rsplit("/", 1)[0] if "/" in t["path"] else "")
              for t in tracks}
    return {"tracks": len(tracks),
            "albums": len(albums),
            "artists": len({t.get("artist", "") for t in tracks if t.get("artist")}),
            "bytes": int(cat.get("bytes") or 0),
            "categories": len(cat.get("categories") or [])}


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
