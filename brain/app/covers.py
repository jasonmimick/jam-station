"""Album enrichment: real cover art + year, from MusicBrainz and the Cover Art Archive.

The ripper gets the audio in; this fills in what makes a record feel like a record — the sleeve
and the year. It runs in the BRAIN (not the ripper) so it enriches on its own schedule and
backfills albums that were ripped before this existed: for each cds/<album> folder we search
MusicBrainz by artist+album, take the release id + date, and pull the front cover. Results are
cached next to the tracks as _album.json + _cover.jpg, so it's a one-time cost per album.

Runs on a background thread, rate-limited (MusicBrainz asks ~1 req/sec). Best-effort — no art
found, or MB down, just means the UI shows the generated tile. Never blocks a request.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from . import config

_GENERIC = re.compile(r"^(\d{1,2})[ .\-_]+audio track$", re.I)   # "01 Audio Track" — an un-named rip
_NUMPREFIX = re.compile(r"^(\d{1,2})[ .\-_]+")

UA = "jam-station/1.0 (https://jam-station.runslab.run)"
_lock = threading.Lock()


def _get(url: str, timeout: int = 20):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout)


def _search_release(artist: str, album: str) -> dict | None:
    q = f'release:"{album}"'
    if artist and "unknown" not in artist.lower():
        q += f' AND artist:"{artist}"'
    url = "https://musicbrainz.org/ws/2/release/?" + urllib.parse.urlencode(
        {"query": q, "fmt": "json", "limit": "1"})
    try:
        rels = json.load(_get(url)).get("releases") or []
    except Exception:
        return None
    if not rels:
        return None
    r = rels[0]
    return {"mbid": r.get("id"), "year": (r.get("date") or "")[:4]}


def _fetch_cover(mbid: str, dest: str) -> bool:
    # CAA redirects to the actual image on archive.org; urllib follows it.
    for size in ("front-500", "front"):
        try:
            data = _get(f"https://coverartarchive.org/release/{mbid}/{size}", timeout=30).read()
        except Exception:
            continue
        if data and len(data) > 1500:                 # guard against a stray error page
            tmp = dest + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            return True
    return False


def _has_generic(folder: str) -> bool:
    try:
        return any(_GENERIC.match(os.path.splitext(f)[0])
                   for f in os.listdir(folder) if f.lower().endswith(".mp3"))
    except Exception:
        return False


def _tracklist(mbid: str) -> dict:
    """{position: title} from the release's recordings — the real song names MusicBrainz has
    even when macOS labelled every track 'Audio Track'."""
    try:
        data = json.load(_get(f"https://musicbrainz.org/ws/2/release/{mbid}?inc=recordings&fmt=json"))
    except Exception:
        return {}
    titles = {}
    for medium in data.get("media", []):
        for t in medium.get("tracks", []):
            try:
                pos = int(t.get("position") or t.get("number"))
            except (TypeError, ValueError):
                continue
            title = t.get("title") or (t.get("recording") or {}).get("title")
            if pos and title and pos not in titles:
                titles[pos] = title
    return titles


def _retitle(folder: str, titles: dict) -> None:
    for f in os.listdir(folder):
        if not f.lower().endswith(".mp3"):
            continue
        m = _GENERIC.match(os.path.splitext(f)[0])         # only rename generic "NN Audio Track"
        if not m:
            continue
        title = titles.get(int(m.group(1)))
        if not title:
            continue
        safe = re.sub(r'[/\\:*?"<>|]', "-", title).strip()
        newname = f"{m.group(1)} {safe}.mp3"
        if newname != f:
            try:
                os.rename(os.path.join(folder, f), os.path.join(folder, newname))
            except Exception:
                pass


def _enrich_one(folder: str, name: str) -> None:
    meta_p = os.path.join(folder, "_album.json")
    cover_p = os.path.join(folder, "_cover.jpg")
    try:
        meta = json.load(open(meta_p)) if os.path.exists(meta_p) else {}
    except Exception:
        meta = {}
    # skip only when nothing's left to do: cover in hand (or unmatchable) AND no generic titles
    cover_done = os.path.exists(cover_p) or (meta.get("tried") and not meta.get("mbid"))
    if meta.get("tried") and cover_done and not _has_generic(folder):
        return

    artist, album = meta.get("artist"), meta.get("album")
    if not album:                                     # derive from "Artist - Album" folder name
        artist, _, album = name.partition(" - ") if " - " in name else ("", "", name)
    if not album or "unknown" in album.lower():
        return

    if not meta.get("mbid"):
        hit = _search_release(artist, album) or {}
        time.sleep(1.1)                               # MusicBrainz rate limit
        meta.setdefault("mbid", hit.get("mbid") or "")
        meta.setdefault("year", hit.get("year") or "")
    if meta.get("mbid") and not os.path.exists(cover_p):
        _fetch_cover(meta["mbid"], cover_p)
        time.sleep(0.4)
    if meta.get("mbid") and _has_generic(folder):     # give the tracks their real names
        titles = _tracklist(meta["mbid"])
        time.sleep(1.1)
        if titles:
            _retitle(folder, titles)

    meta.update({"artist": artist or meta.get("artist", ""), "album": album, "tried": True})
    try:
        with open(meta_p + ".tmp", "w") as f:
            json.dump(meta, f)
        os.replace(meta_p + ".tmp", meta_p)
    except Exception:
        pass


def _enrich_all() -> None:
    base = os.path.join(config.MUSIC_DIR, "cds")
    if not os.path.isdir(base):
        return
    for name in sorted(os.listdir(base)):
        folder = os.path.join(base, name)
        if os.path.isdir(folder):
            try:
                _enrich_one(folder, name)
            except Exception:
                pass


def kick() -> None:
    """Fire a background enrichment pass if one isn't already running. Cheap to call often."""
    if _lock.acquire(blocking=False):
        def run():
            try:
                _enrich_all()
            finally:
                _lock.release()
        threading.Thread(target=run, daemon=True).start()
