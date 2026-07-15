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
    r = rels[0]                       # first match; good enough to name a folder
    ac = r.get("artist-credit") or []
    artist = "".join(a.get("name", "") + a.get("joinphrase", "") for a in ac).strip()
    album = (r.get("title") or "").strip()
    if not album:
        return None
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
