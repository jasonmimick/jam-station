"""A channel that draws from several parts at once: shelf folders, vault artists, named archive.org shows.

cfg = {"parts": [{"source": "library", "folders": ["cds/Pat Metheny - Bright Size Life"], "weight": 3},
                 {"source": "attic", "artist": "John Scofield"},
                 {"source": "archive", "identifiers": ["scofield1992-10-22.schmit.flac16"], "weight": 3}]}

Each top-up picks ONE part at random (by weight, default 1) and returns that part's tracks: a batch of tracks from the shelf or
the vault, or one whole archive.org show. Parts with nothing playable are skipped. Archive shows already played recently
(`exclude`) are avoided until every show has been heard.
"""
from __future__ import annotations

import logging
import random

from . import archive, attic, library

log = logging.getLogger("jam.mix")


def _parts(cfg: dict) -> list[dict]:
    return [p for p in (cfg.get("parts") or []) if isinstance(p, dict)]


def _weight(part: dict) -> float:
    try:
        return max(0.0, float(part.get("weight", 1)))
    except (TypeError, ValueError):
        return 1.0


def _archive_tracks(part: dict, exclude: set[str]) -> list[dict]:
    ids = [i for i in part.get("identifiers") or [] if i]
    fresh = [i for i in ids if i not in exclude] or ids          # everything heard: allow repeats rather than silence
    random.shuffle(fresh)
    for ident in fresh[:3]:                                      # a show that will not load should not silence the channel
        try:
            show = archive.get_show(ident)
        except Exception as e:
            log.warning("mix: could not load archive show %s: %s", ident, e)
            continue
        if show and show.get("tracks"):
            return [{"url": t["url"], "title": t["title"], "artist": str(show.get("creator") or ""),
                     "album": show["title"], "show_id": ident} for t in show["tracks"]]
    return []


def _part_tracks(part: dict, count: int, exclude: set[str]) -> list[dict]:
    src = part.get("source")
    if src == "library":
        return library.pick_tracks(part, count=count)
    if src == "attic":
        return attic.pick_tracks(part, count=count)
    if src == "archive":
        return _archive_tracks(part, exclude)
    return []


def pick_tracks(cfg: dict, count: int = 25, exclude: set[str] | None = None) -> list[dict]:
    parts = [p for p in _parts(cfg) if _weight(p) > 0]
    while parts:
        part = random.choices(parts, weights=[_weight(p) for p in parts])[0]
        tracks = _part_tracks(part, count, exclude or set())
        if tracks:
            return tracks
        parts.remove(part)                                       # nothing playable there right now: try another part
    return []


def playable(cfg: dict) -> bool:
    """Cheap check for the channel list: archive parts count as playable without a network call."""
    for p in _parts(cfg):
        if p.get("source") == "archive" and p.get("identifiers"):
            return True
        if p.get("source") in ("library", "attic") and _part_tracks(p, 1, set()):
            return True
    return False
