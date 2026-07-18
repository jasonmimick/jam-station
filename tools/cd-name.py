#!/usr/bin/env python3
"""Name the audio CD in the drive, from its table of contents.

macOS looks up track TITLES (they arrive as the .aiff filenames) but leaves album and artist
blank — no CD-Text, nothing in Spotlight. The one thing always present is the physical TOC in
/Volumes/Audio CD/.TOC.plist, so we ask the disc what it physically is and let MusicBrainz
answer. Prints one line, "Artist\tAlbum", or nothing at all — a blank stdout means "couldn't
identify it", and the caller falls back to a dated folder rather than inventing a wrong name.

Two-step lookup, because the fuzzy TOC search CANNOT be trusted on its own:

1. EXACT — compute the MusicBrainz disc ID (a hash of the TOC) and look it up. A hit means
   this exact pressing is in the database. Done.
2. FUZZY — the raw-TOC search matches on track count and rough TOTAL length only. That is
   how "Are You Experienced" (60:22) got named "Fiddler's Green — 25 Blarney Roses" (59:48):
   same 17 tracks, totals 34s apart, per-track starts up to 128s apart. So a fuzzy candidate
   is only believed after fetching its actual disc offsets and checking EVERY track starts
   within DRIFT_MAX_S of ours. Real pressing variants drift well under a second; a
   different-album coincidence drifts by whole songs. No candidate survives → blank stdout.

Standalone and dependency-free (stdlib urllib): the ripper and the watcher both shell out to it.
"""
from __future__ import annotations   # the mini runs python 3.9; keep the `X | None` hints lazy

import base64
import hashlib
import json
import plistlib
import sys
import time
import urllib.parse
import urllib.request

UA = "jam-station/1.0 (https://jam-station.runslab.run)"
MB = "https://musicbrainz.org/ws/2"
DRIFT_MAX_S = 5.0    # max per-track start drift to accept a fuzzy candidate (75 sectors = 1s)
FUZZY_CANDIDATES = 5  # how many fuzzy candidates are worth a disc-offset check


def disc_volume() -> str | None:
    import glob
    for v in glob.glob("/Volumes/*/"):
        if glob.glob(v + "*.aiff"):
            return v
    return None


def toc_parts(vol: str) -> list[int] | None:
    """[first, last, leadout, offset1, ...] in MusicBrainz sectors."""
    try:
        toc = plistlib.load(open(vol + ".TOC.plist", "rb"))
        s = toc["Sessions"][0]
        # MusicBrainz sectors are LBA + 150 (the 2-second pregap; MSF vs LBA addressing).
        offs = [t["Start Block"] + 150 for t in s["Track Array"] if 1 <= t.get("Point", 0) <= 99]
        return [s["First Track"], s["Last Track"], s["Leadout Block"] + 150, *offs]
    except Exception:
        return None


def mb_discid(parts: list[int]) -> str:
    """The exact MusicBrainz disc ID: SHA-1 over the TOC in their fixed-width hex layout,
    base64 with the URL-hostile chars swapped (+/= -> ._-)."""
    first, last, leadout, offs = parts[0], parts[1], parts[2], parts[3:]
    h = hashlib.sha1()
    h.update(("%02X%02X%08X" % (first, last, leadout)).encode())
    for i in range(99):
        h.update(("%08X" % (offs[i] if i < len(offs) else 0)).encode())
    return base64.b64encode(h.digest()).decode().translate(str.maketrans("+/=", "._-"))


def _get(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        return json.load(urllib.request.urlopen(req, timeout=12))
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


def _media_count(r: dict) -> int:
    m = r.get("media")
    return len(m) if isinstance(m, list) and m else 1


# prefer a real standalone album: not a box-set title, fewest discs, then earliest release.
def _rank(r: dict):
    return (1 if _is_boxset(r.get("title")) else 0, _media_count(r), r.get("date") or "9999")


def _name(r: dict) -> tuple[str, str] | None:
    album = (r.get("title") or "").strip()
    if not album or _is_boxset(album):
        return None
    ac = r.get("artist-credit") or []
    artist = "".join(a.get("name", "") + a.get("joinphrase", "") for a in ac).strip()
    return artist or "Unknown Artist", album


def _drift_s(parts: list[int], release_id: str) -> float | None:
    """Worst per-track start drift (seconds) between our disc and the closest disc attached
    to this release. None = release has no comparable disc (different track count / no TOCs)."""
    ours = parts[3:]
    data = _get(f"{MB}/release/{release_id}?inc=discids&fmt=json")
    if not data:
        return None
    best = None
    for medium in data.get("media") or []:
        for disc in medium.get("discs") or []:
            theirs = disc.get("offsets") or []
            if len(theirs) != len(ours):
                continue
            worst = max(abs(a - b) for a, b in zip(theirs, ours)) / 75.0
            if best is None or worst < best:
                best = worst
    return best


def lookup(parts: list[int]) -> tuple[str, str] | None:
    # 1) exact: this pressing's disc ID is in the database — trustworthy, no drift check.
    data = _get(f"{MB}/discid/{mb_discid(parts)}?inc=artists&fmt=json&cdstubs=no")
    rels = (data or {}).get("releases") or []
    if rels:
        # If even the best match is a box set, DON'T name it that — return nothing so the caller
        # falls back to a dated 'Unknown' folder, instead of committing a wrong box-set name.
        return _name(sorted(rels, key=_rank)[0])

    # 2) fuzzy: discid '-' means "match this raw TOC instead". Candidates here are only
    #    length-alike, so each must prove its per-track offsets before we believe it.
    tocstr = "+".join(str(x) for x in parts)
    q = urllib.parse.urlencode({"toc": tocstr, "inc": "artists", "fmt": "json"})
    data = _get(f"{MB}/discid/-?{q}")
    rels = [r for r in (data or {}).get("releases") or [] if not _is_boxset(r.get("title"))]
    verified = []
    for r in sorted(rels, key=_rank)[:FUZZY_CANDIDATES]:
        if verified:
            time.sleep(1)                       # MusicBrainz asks for 1 req/sec
        d = _drift_s(parts, r.get("id", ""))
        if d is not None and d <= DRIFT_MAX_S:
            verified.append((d, r))
    if not verified:
        return None
    return _name(min(verified, key=lambda x: x[0])[1])


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--toc":
        # test/debug: name a TOC string ("first+last+leadout+off1+...") without a disc in the drive
        parts = [int(x) for x in sys.argv[2].split("+")]
    else:
        vol = disc_volume()
        if not vol:
            return 1
        parts = toc_parts(vol)
    if not parts or len(parts) < 4:
        return 1
    hit = lookup(parts)
    if not hit:
        return 1
    artist, album = hit
    sys.stdout.write(f"{artist}\t{album}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
