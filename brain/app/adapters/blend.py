"""Genre-balanced blend across every local source (library + attic).

Reusable picker, not a one-off for RADIO100: `pick_tracks(cfg)` stratifies by
genre/category FIRST, then round-robins one track per bucket per round. A flat
random.sample() over the merged pool (what library.pick_tracks/attic.pick_tracks
each do on their own) would let whichever bucket has the most tracks dominate —
900 ripped jazz tracks vs. 3 rain field recordings is not "all genres", it's
mostly jazz. Round-robin gives every bucket - including whatever `_genres.json`
tag the owner made up by hand - equal odds until it runs out.

`cfg["sources"]` (default both) is the reuse hook: a future channel can blend
just one source genre-balanced (still useful — library.pick_tracks is flat),
or add a third source later without touching the algorithm.
"""
from __future__ import annotations

import random

from . import attic, library

UNTAGGED = "untagged"


def _library_buckets() -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {}
    # root="" walks the WHOLE music dir (cds/, fusion/, inbox/, ...), not just
    # list_albums()'s "cds" default — RADIO100 means the entire shelf.
    for alb in library.list_albums(root=""):
        tracks = library.album_tracks(alb["dir"])
        if not tracks:
            continue
        for g in (alb.get("genres") or [UNTAGGED]):
            buckets.setdefault((g or UNTAGGED).strip().lower(), []).extend(tracks)
    return buckets


def _attic_buckets() -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {}
    for raw in attic._catalog().get("tracks") or []:
        t = attic._track(raw)
        for g in (raw.get("genres") or [UNTAGGED]):
            buckets.setdefault((g or UNTAGGED).strip().lower(), []).append(t)
    return buckets


_BUCKET_FNS = {"library": _library_buckets, "attic": _attic_buckets}


def _buckets(cfg: dict) -> dict[str, list[dict]]:
    merged: dict[str, list[dict]] = {}
    for src in cfg.get("sources") or ("library", "attic"):
        fn = _BUCKET_FNS.get(src)
        if not fn:
            continue
        for genre, tracks in fn().items():
            merged.setdefault(genre, []).extend(tracks)
    return merged


def pick_tracks(cfg: dict, count: int = 25) -> list[dict]:
    buckets = _buckets(cfg)
    if not buckets:
        return []
    for tracks in buckets.values():
        random.shuffle(tracks)
    keys = list(buckets.keys())
    random.shuffle(keys)
    out: list[dict] = []
    idx = {k: 0 for k in keys}
    while len(out) < count:
        progressed = False
        for k in keys:
            if idx[k] < len(buckets[k]):
                out.append(buckets[k][idx[k]])
                idx[k] += 1
                progressed = True
                if len(out) >= count:
                    break
        if not progressed:
            break
    random.shuffle(out)  # genre-balanced pick order, but not genre-grouped on air
    return out
