"""Source adapter for your own music library (the /music folder).

This is where the 70s fusion lives — music you own/ripped, served straight
from disk. Liquidsoap mounts the same folder read-only, so queue entries are
urls under /music/, NOT file paths — see config.INTERNAL_URL for why.
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
from urllib.parse import quote

log = logging.getLogger("jam.library")


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
            if m.get("genres") is not None:
                extra["genres"] = m["genres"]
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
    if cfg.get("genre"):
        # a section channel: random songs from every record filed under the genre
        want = cfg["genre"].strip().lower()
        files = []
        for alb in list_albums():
            if any((g or "").lower() == want for g in alb.get("genres") or []):
                folder = os.path.join(config.MUSIC_DIR, alb["dir"])
                try:
                    files += [os.path.join(folder, f) for f in os.listdir(folder)
                              if f.lower().endswith(config.AUDIO_EXTENSIONS)]
                except OSError:
                    pass
    else:
        files = _scan(cfg.get("folders"))
    if not files:
        log.info("pick_tracks: no files (query=%s)", cfg)
        return []
    picks = random.sample(files, min(count, len(files)))
    out = [_meta(p) for p in picks]
    log.info("pick_tracks: query=%s pool=%d picked=%d albums=%d",
             cfg, len(files), len(out), len({t["album"] for t in out}))
    return out


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
            "mtime": os.path.getmtime(dirpath),                  # for newest-first ordering
            **_folder_extra(dirpath, rel),                       # year / cover_url / learn_url
        })
    out.sort(key=lambda a: a["mtime"], reverse=True)             # newest-ripped disc first
    return out


def art_slug(t: str) -> str:
    """A photo 'type' -> a safe filename slug. 'Tracklist' -> 'tracklist', 'Back Insert' ->
    'back-insert'. Lowercase [a-z0-9-] only, capped so a wild label can't blow out the name."""
    s = re.sub(r"[^a-z0-9-]+", "-", (t or "").strip().lower())
    return s.strip("-")[:24].strip("-")


def album_images(rel_dir: str) -> list[dict]:
    """Every image filed with an album: the front cover (_cover.jpg) first if it exists, then
    any owner-added _art-<type>.jpg (tracklist / back / disc / …), sorted by type for a stable
    strip. `rel_dir` is caller-supplied — same escape-guard as album_tracks before touching disk."""
    base = os.path.realpath(config.MUSIC_DIR)
    full = os.path.realpath(os.path.join(base, rel_dir))
    if full != base and not full.startswith(base + os.sep):
        return []                                    # ../../ escape — refused
    if not os.path.isdir(full):
        return []
    rel = os.path.relpath(full, base)
    out = []
    if os.path.exists(os.path.join(full, "_cover.jpg")):
        out.append({"type": "front", "url": "/music/" + quote(rel + "/_cover.jpg")})
    extras = []
    try:
        for fn in os.listdir(full):
            m = re.match(r"^_art-([a-z0-9-]+)\.jpg$", fn)
            if m:
                extras.append((m.group(1), fn))
    except OSError:
        pass
    for typ, fn in sorted(extras):
        out.append({"type": typ, "url": "/music/" + quote(rel + "/" + fn)})
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


# ── genres: the shelf's sections ─────────────────────────────────────────

def genre_counts() -> list[dict]:
    """The sections that exist on this shelf, biggest first — whatever the
    enricher mapped plus whatever the owner curated. Buckets emerge from the
    records; there is no registry to maintain."""
    counts: dict[str, int] = {}
    for alb in list_albums():
        for g in alb.get("genres") or []:
            counts[g] = counts.get(g, 0) + 1
    return [{"name": g, "count": n}
            for g, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


def build_mix(genre: str, count: int = 30) -> list[dict]:
    """A shuffled tracklist across every album in a section — 'a jazz mix from
    the shelf'. Show-shaped by the caller, so every client plays it through the
    machinery it already has."""
    import random
    want = (genre or "").strip().lower()
    tracks: list[dict] = []
    for alb in list_albums():
        if any((g or "").lower() == want for g in alb.get("genres") or []):
            tracks.extend(album_tracks(alb["dir"]))
    random.shuffle(tracks)
    return tracks[:max(1, min(count, 100))]


def set_genres(rel_dir: str, genres: list[str]) -> bool:
    """Owner curation: pin an album's sections (any labels at all). Marks the
    record owner-set so the enricher never second-guesses it. Folder mtime IS
    'date added' — writing the sidecar must not bump the gallery order."""
    base = os.path.realpath(config.MUSIC_DIR)
    full = os.path.realpath(os.path.join(base, rel_dir))
    if full != base and not full.startswith(base + os.sep):
        return False
    if not os.path.isdir(full):
        return False
    clean = [g.strip() for g in genres if g and g.strip()][:5]
    meta_p = os.path.join(full, "_album.json")
    try:
        folder_mtime = os.stat(full).st_mtime
    except OSError:
        folder_mtime = None
    try:
        meta = json.load(open(meta_p)) if os.path.exists(meta_p) else {}
    except Exception:
        meta = {}
    meta["genres"] = clean
    meta["genres_owner"] = True
    try:
        with open(meta_p + ".tmp", "w") as f:
            json.dump(meta, f)
        os.replace(meta_p + ".tmp", meta_p)
    except Exception:
        return False
    if folder_mtime is not None:
        try:
            os.utime(full, (folder_mtime, folder_mtime))
        except OSError:
            pass
    return True
