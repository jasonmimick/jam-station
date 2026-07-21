#!/usr/bin/env python3
"""attic-genres — fill a vault root's _genres.json from MusicBrainz artist tags.

Usage (on the mini host, per root):
    python3 attic-genres.py /tmp/tc-afp/attic-vault/drive-03-inesse-reco/Music

Walks the root's top-level artist folders, looks each artist up on MusicBrainz
(1 req/s per their rate limit — ~345 artists takes ~6 min), maps fine tags down
into the same coarse BUCKETS the brain's covers.py uses, and writes
<root>/_genres.json: {"Artist Name": ["Jazz", ...]}.

The file is the source of truth and the OWNER's to edit: this tool only fills
blanks — an artist already in the file (even with []) is never touched, so
hand-curation survives re-runs. attic-server.py reads the sidecar on its next
catalog walk; categories emerge from whatever genres are present.

Stdlib only, like every attic tool.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

# Copied from brain/app/covers.py BUCKETS — keep in sync (coarse, record-store sections).
BUCKETS = [
    ("Jazz",       ("jazz", "bebop", "bop", "swing", "big band", "fusion")),
    ("Blues",      ("blues",)),
    ("Classical",  ("classical", "baroque", "romantic era", "opera", "symphony", "chamber")),
    ("Rock",       ("rock", "punk", "metal", "grunge", "psychedelic", "new wave", "indie")),
    ("Folk",       ("folk", "singer-songwriter", "americana", "bluegrass", "newgrass")),
    ("Country",    ("country",)),
    ("Soul/Funk",  ("soul", "funk", "r&b", "rhythm and blues", "motown", "disco")),
    ("Hip-Hop",    ("hip hop", "hip-hop", "rap")),
    ("Electronic", ("electronic", "techno", "house", "ambient", "downtempo", "trip hop")),
    ("Reggae",     ("reggae", "ska", "dub")),
    ("World",      ("world", "latin", "afrobeat", "klezmer", "gamelan", "celtic", "flamenco")),
    ("Pop",        ("pop",)),
]


def bucketize(tags: list[str]) -> list[str]:
    out = []
    for tag in tags:
        t = (tag or "").lower()
        for bucket, needles in BUCKETS:
            if any(n in t for n in needles) and bucket not in out:
                out.append(bucket)
    return out[:3]


def mb_artist_genres(name: str) -> list[str]:
    """Search MB for the artist, take the top hit's tags+genres, bucketized.
    A miss (or a top hit with a weak score) returns [] — an honest blank beats
    a wrong section, same principle as CD naming."""
    q = urllib.parse.urlencode({"query": f'artist:"{name}"', "fmt": "json", "limit": "1",
                                "inc": "tags genres"})
    req = urllib.request.Request(
        f"https://musicbrainz.org/ws/2/artist?{q}",
        headers={"User-Agent": "jam-station-attic/0.1 (personal home radio)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
    except Exception:
        return []
    artists = data.get("artists") or []
    if not artists or int(artists[0].get("score", 0)) < 90:
        return []
    top = artists[0]
    names = [g.get("name", "") for g in (top.get("genres") or [])]
    names += [t.get("name", "") for t in sorted(
        top.get("tags") or [], key=lambda t: -(t.get("count") or 0))]
    return bucketize(names)


def main() -> None:
    if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]):
        sys.exit(f"usage: {sys.argv[0]} <vault-music-root>")
    root = sys.argv[1]
    sidecar = os.path.join(root, GENRES_FILE := "_genres.json")
    try:
        with open(sidecar) as f:
            known = json.load(f)
    except Exception:
        known = {}

    artists = sorted(d for d in os.listdir(root)
                     if os.path.isdir(os.path.join(root, d)) and not d.startswith("."))
    todo = [a for a in artists if a not in known]
    print(f"{len(artists)} artist folders, {len(known)} already mapped, {len(todo)} to look up")

    done = 0
    for name in todo:
        known[name] = mb_artist_genres(name)
        done += 1
        print(f"[{done}/{len(todo)}] {name}: {', '.join(known[name]) or '(no match)'}", flush=True)
        # write as we go — a killed run keeps its progress (resumable and boring)
        with open(sidecar + ".tmp", "w") as f:
            json.dump(known, f, indent=1, sort_keys=True, ensure_ascii=False)
        os.replace(sidecar + ".tmp", sidecar)
        time.sleep(1.1)                     # MB rate limit: 1 req/s, stay polite

    tagged = sum(1 for v in known.values() if v)
    print(f"done: {tagged}/{len(known)} artists carry a section -> {sidecar}")


if __name__ == "__main__":
    main()
