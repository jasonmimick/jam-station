"""The record wall: Jason's LP collection, synced from Discogs.

Catalog only — vinyl has no audio to stream; this feeds the browsable wall, and
phase 2's playable twins point at audio the station already owns
(DESIGN-vinyl.md). Same sidecar philosophy as the CD shelf: everything lands as
plain files in the music volume —

    /music/_vinyl/collection.json       the catalog, one greppable file
    /music/_vinyl/covers/<release>.jpg  mirrored thumbnails (Discogs image URLs
                                        need auth + rate-limit; fetch once)

Sync is idempotent and additive; a failed sync leaves the previous cache
untouched (offline is never an empty wall). Token via DISCOGS_TOKEN (slab
secret) — the username comes from the token's own identity, no second config.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from . import config

log = logging.getLogger("jam.vinyl")

API = "https://api.discogs.com"
UA = "jam-station/1.0 (https://jam-station.runslab.run)"
_lock = threading.Lock()

_ARTIST_DISAMBIG = re.compile(r"\s*\(\d+\)\s*$")   # Discogs "Artist (2)" suffixes


def _dir() -> str:
    return os.path.join(config.MUSIC_DIR, "_vinyl")


def _collection_path() -> str:
    return os.path.join(_dir(), "collection.json")


def _get(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Authorization": f"Discogs token={config.DISCOGS_TOKEN}",
    })
    return urllib.request.urlopen(req, timeout=timeout)


def _shape(release: dict) -> dict:
    b = release.get("basic_information") or {}
    artists = b.get("artists") or []
    artist = _ARTIST_DISAMBIG.sub("", (artists[0].get("name") if artists else "") or "")
    return {
        "id": release.get("id") or b.get("id"),
        "artist": artist.strip(),
        "title": (b.get("title") or "").strip(),
        "year": b.get("year") or None,
        "styles": b.get("styles") or [],
        "genres": b.get("genres") or [],
        "thumb": b.get("cover_image") or b.get("thumb") or "",
    }


def sync() -> dict:
    """Pull the whole collection; then mirror any covers we don't have yet.
    Runs minutes on first sync (rate-limited image fetches), seconds after."""
    if not config.DISCOGS_TOKEN:
        log.info("sync: no DISCOGS_TOKEN — vinyl wall disabled")
        return {"ok": False, "reason": "no token"}
    who = json.load(_get(f"{API}/oauth/identity"))
    username = who["username"]
    records, page, pages = [], 1, 1
    while page <= pages:
        url = (f"{API}/users/{urllib.parse.quote(username)}/collection/folders/0/releases?"
               + urllib.parse.urlencode({"per_page": 100, "page": page}))
        data = json.load(_get(url))
        pages = (data.get("pagination") or {}).get("pages", 1)
        records += [_shape(r) for r in data.get("releases") or []]
        page += 1
        time.sleep(1.1)                        # stay friendly to the rate limit
    records = [r for r in records if r["id"] and (r["title"] or r["artist"])]

    os.makedirs(_dir(), exist_ok=True)
    payload = {"synced_at": int(time.time()), "username": username, "records": records}
    tmp = _collection_path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, _collection_path())
    log.info("sync: %d records for %s", len(records), username)

    covers_dir = os.path.join(_dir(), "covers")
    os.makedirs(covers_dir, exist_ok=True)
    fetched = 0
    for r in records:
        dest = os.path.join(covers_dir, f"{r['id']}.jpg")
        if not r["thumb"] or os.path.exists(dest):
            continue
        try:
            data = _get(r["thumb"], timeout=30).read()
            if data and len(data) > 800:
                with open(dest + ".tmp", "wb") as f:
                    f.write(data)
                os.replace(dest + ".tmp", dest)
                fetched += 1
        except Exception:
            pass                               # a missing thumb is a generated tile
        time.sleep(1.1)
    log.info("sync: mirrored %d new covers", fetched)
    return {"ok": True, "records": len(records), "new_covers": fetched}


def kick(max_age_hours: float = 24) -> None:
    """Background sync if the cache is stale (or absent). Cheap to call often."""
    if not config.DISCOGS_TOKEN:
        return
    try:
        age = time.time() - os.stat(_collection_path()).st_mtime
        if age < max_age_hours * 3600:
            return
    except OSError:
        pass                                   # no cache yet — sync
    if _lock.acquire(blocking=False):
        def run():
            try:
                sync()
            except Exception as e:
                log.warning("sync failed: %s", e)
            finally:
                _lock.release()
        threading.Thread(target=run, daemon=True).start()


def records() -> list[dict]:
    """The wall, from cache. cover_url only when the thumbnail is mirrored —
    it serves through the members-only /music route like everything else."""
    try:
        with open(_collection_path()) as f:
            data = json.load(f)
    except Exception:
        return []
    covers_dir = os.path.join(_dir(), "covers")
    out = []
    for r in data.get("records") or []:
        rec = dict(r)
        rec.pop("thumb", None)                 # the Discogs URL is not for clients
        if os.path.exists(os.path.join(covers_dir, f"{r['id']}.jpg")):
            rec["cover_url"] = f"/music/_vinyl/covers/{r['id']}.jpg"
        out.append(rec)
    out.sort(key=lambda r: ((r["artist"] or "~").lower(), (r["title"] or "").lower()))
    return out


def sections(min_count: int = 2) -> list[dict]:
    """The wall's sections from Discogs STYLES (finer than genres); a record
    with no styles falls back to its genres so nothing is unfindable."""
    counts: dict[str, int] = {}
    for r in records():
        for s in (r.get("styles") or r.get("genres") or []):
            counts[s] = counts.get(s, 0) + 1
    return [{"name": s, "count": n}
            for s, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            if n >= min_count]
