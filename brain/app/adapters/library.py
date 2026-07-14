"""Source adapter for your own music library (the /music folder).

This is where the 70s fusion lives — music you own/ripped, served straight
from disk. Liquidsoap mounts the same folder read-only, so queue entries are
urls under /music/, NOT file paths — see config.INTERNAL_URL for why.
"""
from __future__ import annotations

import os
import random
import re
from urllib.parse import quote

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
        folder = os.path.basename(os.path.dirname(p))

        # The path IS the tags. Two conventions, and a ripped CD writes the second:
        #   "Artist - Title.mp3"                     (a loose file in a folder)
        #   "Artist - Album/07 Title.mp3"            (what rip-cd.sh lays down)
        # Without the second, every ripped track came out titled "04 Bonnie & Slyde" with
        # no artist at all — a track number in the title and a blank name on the board.
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

        tracks.append({
            # PERCENT-ENCODE. "Béla Fleck and the Flecktones - UFO Tofu/09 Life Without
            # Elvis.mp3" is a perfectly good FILENAME and an illegal URL — a url cannot
            # hold a raw space. Browsers paper over it by encoding on the way out;
            # liquidsoap does not, and it's the one that has to fetch this. quote() leaves
            # "/" alone, so the path shape survives.
            "url": "/music/" + quote(os.path.relpath(p, config.MUSIC_DIR)),
            "title": title.strip(),
            "artist": artist.strip(),
            "album": album.strip(),
        })
    return tracks
