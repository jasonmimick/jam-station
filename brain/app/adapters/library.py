"""Source adapter for your own music library (the /music folder).

This is where the 70s fusion lives — music you own/ripped, served straight
from disk. Liquidsoap mounts the same folder read-only, so queue entries are
urls under /music/, NOT file paths — see config.INTERNAL_URL for why.
"""
from __future__ import annotations

import json
import os
import random
import re
from urllib.parse import quote


def _folder_extra(folder_abs: str, rel_dir: str) -> dict:
    """Enrichment covers.py cached beside the tracks: year, a MusicBrainz link, and the real
    front cover if it fetched one. Absent = the UI falls back to the generated tile."""
    extra = {}
    try:
        mp = os.path.join(folder_abs, "_album.json")
        if os.path.exists(mp):
            with open(mp) as f:
                m = json.load(f)
            if m.get("year"):
                extra["year"] = m["year"]
            if m.get("mbid"):
                extra["learn_url"] = "https://musicbrainz.org/release/" + m["mbid"]
    except Exception:
        pass
    if os.path.exists(os.path.join(folder_abs, "_cover.jpg")):
        extra["cover_url"] = "/music/" + quote(rel_dir + "/_cover.jpg")
    return extra

from .. import config


def _scan(folders: list[str] | None) -> list[str]:
    roots = []
    if folders:
        roots = [os.path.join(config.MUSIC_DIR, f) for f in folders]
    else:
        roots = [config.MUSIC_DIR]
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if fn.lower().endswith(config.AUDIO_EXTENSIONS):
                    found.append(os.path.join(dirpath, fn))
    return found


def _meta(p: str) -> dict:
    """One file -> a playable track. The path IS the tags. Two conventions, and a ripped CD
    writes the second:
        "Artist - Title.mp3"                     (a loose file in a folder)
        "Artist - Album/07 Title.mp3"            (what rip-cd.sh lays down)
    Without the second, every ripped track came out titled "04 Bonnie & Slyde" with no artist
    at all — a track number in the title and a blank name on the board."""
    base = os.path.splitext(os.path.basename(p))[0]
    folder = os.path.basename(os.path.dirname(p))
    artist, _, title = base.partition(" - ")
    if not title:
        artist, title = "", base
    album = folder
    m = re.match(r"^(\d{1,2})[ .\-_]+(.+)$", title)   # strip a leading track number
    if m and not artist:
        title = m.group(2)
        a, sep, alb = folder.partition(" - ")          # "Artist - Album"
        if sep:
            artist, album = a.strip(), alb.strip()
    return {
        # PERCENT-ENCODE. "…UFO Tofu/09 Life Without Elvis.mp3" is a fine FILENAME and an
        # illegal URL — a url cannot hold a raw space. Browsers paper over it; liquidsoap
        # does not, and it's the one that has to fetch this. quote() leaves "/" alone.
        "url": "/music/" + quote(os.path.relpath(p, config.MUSIC_DIR)),
        "title": title.strip(),
        "artist": artist.strip(),
        "album": album.strip(),
    }


def pick_tracks(cfg: dict, count: int = 25) -> list[dict]:
    files = _scan(cfg.get("folders"))
    if not files:
        return []
    picks = random.sample(files, min(count, len(files)))
    return [_meta(p) for p in picks]


def list_albums(root: str = "cds") -> list[dict]:
    """The catalog: one entry per album FOLDER under music/<root>, not one per track. This is
    the answer to 'don't make a channel per CD' — every ripped disc lands in one browsable
    shelf. Sorted by artist then album so the catalog reads like a record crate."""
    base = os.path.join(config.MUSIC_DIR, root)
    out = []
    if not os.path.isdir(base):
        return out
    for dirpath, _dirs, files in os.walk(base):
        audio = sorted(f for f in files if f.lower().endswith(config.AUDIO_EXTENSIONS))
        if not audio:
            continue
        first = _meta(os.path.join(dirpath, audio[0]))
        rel = os.path.relpath(dirpath, config.MUSIC_DIR)
        out.append({
            "dir": rel,                                          # e.g. "cds/Béla… - UFO Tofu"
            "artist": first["artist"],
            "album": first["album"],
            "tracks": len(audio),
            **_folder_extra(dirpath, rel),                       # year / cover_url / learn_url
        })
    out.sort(key=lambda a: (a["artist"].lower(), a["album"].lower()))
    return out


def album_tracks(rel_dir: str) -> list[dict]:
    """One album's tracks, IN ORDER (filenames are '07 Title', so a filename sort is the
    running order). `rel_dir` is caller-supplied — resolve it and refuse anything that climbs
    out of MUSIC_DIR before touching disk."""
    base = os.path.realpath(config.MUSIC_DIR)
    full = os.path.realpath(os.path.join(base, rel_dir))
    if full != base and not full.startswith(base + os.sep):
        return []                                    # ../../etc — not on my watch
    if not os.path.isdir(full):
        return []
    files = sorted(f for f in os.listdir(full) if f.lower().endswith(config.AUDIO_EXTENSIONS))
    extra = _folder_extra(full, os.path.relpath(full, base))     # year/cover/learn on every track
    return [{**_meta(os.path.join(full, f)), **extra} for f in files]
