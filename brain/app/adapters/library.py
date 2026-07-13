"""Source adapter for your own music library (the /music folder).

This is where the 70s fusion lives — music you own/ripped, served straight
from disk. Liquidsoap mounts the same folder read-only, so queue entries are
plain file paths.
"""
from __future__ import annotations

import os
import random

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


def pick_tracks(cfg: dict, count: int = 25) -> list[dict]:
    files = _scan(cfg.get("folders"))
    if not files:
        return []
    picks = random.sample(files, min(count, len(files)))
    tracks = []
    for p in picks:
        base = os.path.splitext(os.path.basename(p))[0]
        # cheap "Artist - Title" split; navidrome does real tagging for browsing
        artist, _, title = base.partition(" - ")
        if not title:
            artist, title = "", base
        tracks.append({
            "url": p,
            "title": title.strip(),
            "artist": artist.strip(),
            "album": os.path.basename(os.path.dirname(p)),
        })
    return tracks
