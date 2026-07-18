#!/usr/bin/env python3
"""Name the audio CD in the drive, from its table of contents.

macOS looks up track TITLES (they arrive as the .aiff filenames) but leaves album and artist
blank — no CD-Text, nothing in Spotlight. The one thing always present is the physical TOC in
/Volumes/Audio CD/.TOC.plist, and that is exactly what MusicBrainz's fuzzy disc lookup takes.
So we don't guess from track names; we ask the disc what it physically is and let the database
answer. Prints one line, "Artist\tAlbum", or nothing at all — a blank stdout means "couldn't
identify it", and the caller falls back to a dated folder rather than inventing a wrong name.

Standalone and dependency-free (stdlib urllib): the ripper and the watcher both shell out to it.
"""
from __future__ import annotations   # the mini runs python 3.9; keep the `X | None` hints lazy

import json
import plistlib
import sys
import urllib.parse
import urllib.request

UA = "jam-station/1.0 (https://jam-station.runslab.run)"


def disc_volume() -> str | None:
    import glob
    for v in glob.glob("/Volumes/*/"):
        if glob.glob(v + "*.aiff"):
            return v
    return None


def toc_string(vol: str) -> str | None:
    try:
        toc = plistlib.load(open(vol + ".TOC.plist", "rb"))
        s = toc["Sessions"][0]
        # MusicBrainz sectors are LBA + 150 (the 2-second pregap; MSF vs LBA addressing).
        offs = [t["Start Block"] + 150 for t in s["Track Array"] if 1 <= t.get("Point", 0) <= 99]
        parts = [s["First Track"], s["Last Track"], s["Leadout Block"] + 150, *offs]
        return "+".join(str(x) for x in parts)
    except Exception:
        return None


# Album titles that mean "this is a box set / reissue compilation", not the actual album. The
# raw-TOC lookup matches the standalone album AND any box set that reused the same disc master, and
# MusicBrainz doesn't order them helpfully — so a disc kept landing as "The Complete Columbia Album
# Collection" (really E.S.P.) or "The Triple Album Collection" (really The Real Thing).
_BOXSET = ("complete", "collection", "anthology", "box set", "boxset",
           "classic albums", "original album", "triple album", "double album", "the works")


def _is_boxset(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in _BOXSET)


def lookup(tocstr: str) -> tuple[str, str] | None:
    q = urllib.parse.urlencode({"toc": tocstr, "inc": "artists", "fmt": "json"})
    # discid '-' means "I have no disc id, match this raw TOC instead" — the fuzzy lookup.
    url = f"https://musicbrainz.org/ws/2/discid/-?{q}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        data = json.load(urllib.request.urlopen(req, timeout=12))
    except Exception:
        return None
    rels = data.get("releases") or []
    if not rels:
        return None

    def media_count(r: dict) -> int:
        m = r.get("media")
        return len(m) if isinstance(m, list) and m else 1

    # prefer a real standalone album: not a box-set title, fewest discs, then earliest release.
    def rank(r: dict):
        return (1 if _is_boxset(r.get("title")) else 0, media_count(r), r.get("date") or "9999")

    r = sorted(rels, key=rank)[0]
    album = (r.get("title") or "").strip()
    # If even the best match is a box set, DON'T name it that — return nothing so the caller falls
    # back to a dated 'Unknown' folder you can rename, instead of committing a wrong box-set name.
    if not album or _is_boxset(album):
        return None
    ac = r.get("artist-credit") or []
    artist = "".join(a.get("name", "") + a.get("joinphrase", "") for a in ac).strip()
    return artist or "Unknown Artist", album


def main() -> int:
    vol = disc_volume()
    if not vol:
        return 1
    tocstr = toc_string(vol)
    if not tocstr:
        return 1
    hit = lookup(tocstr)
    if not hit:
        return 1
    artist, album = hit
    sys.stdout.write(f"{artist}\t{album}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
