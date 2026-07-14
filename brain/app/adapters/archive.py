"""Source adapter for the Internet Archive's Live Music Archive.

No API key needed. Three endpoints do everything:
  - advancedsearch.php  : find shows (with community avg_rating!)
  - /metadata/<id>      : track list + files for one show
  - /download/<id>/<f>  : the actual MP3s, plain HTTP
"""
from __future__ import annotations

import random
import re
import urllib.parse

import httpx

BASE = "https://archive.org"
_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "jam-station/0.1 (personal home radio)"},
        )
    return _client


def set_client(c: httpx.Client) -> None:
    """Test hook: inject a client with a MockTransport."""
    global _client
    _client = c


def build_query(collections=None, free_text=None, year=None, min_rating=None) -> str:
    parts = []
    if collections:
        if isinstance(collections, str):
            collections = [collections]
        joined = " OR ".join(collections)
        parts.append(f"collection:({joined})")
    else:
        parts.append("mediatype:(etree)")
    if year:
        parts.append(f"year:({year})")
    if min_rating:
        parts.append(f"avg_rating:[{min_rating} TO 5]")
    if free_text:
        parts.append(f"({free_text})")
    return " AND ".join(parts)


def search_shows(collections=None, free_text=None, year=None, min_rating=None,
                 rows=40, sort="avg_rating desc") -> list[dict]:
    q = build_query(collections, free_text, year, min_rating)
    params = {
        "q": q,
        "fl[]": ["identifier", "title", "date", "year", "venue", "coverage",
                 "avg_rating", "num_reviews", "source"],
        "sort[]": sort,
        "rows": str(rows),
        "page": "1",
        "output": "json",
    }
    r = client().get(f"{BASE}/advancedsearch.php", params=params)
    r.raise_for_status()
    return r.json().get("response", {}).get("docs", [])


def _track_sort_key(f: dict):
    track = f.get("track") or ""
    m = re.search(r"\d+", str(track))
    if m:
        return (0, int(m.group()), f.get("name", ""))
    return (1, 0, f.get("name", ""))


# A tape whose tracks are called "goose2018-12-11t01" makes the setlist useless —
# and the setlist is the whole point of knowing where you are in a show. Plenty of
# Archive items carry NO per-file title on any format, but do spell the songs out
# in the item description. Mine it, and only trust it when the count lines up.

_HTML = re.compile(r"<[^>]+>")
# lines that are clearly not songs: the band, the date, the venue, taper credits
_NOT_A_SONG = re.compile(
    r"^\s*$|^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\s*$|"
    r"(taper|source|lineage|transfer|recorded|mics?|matrix|sbd|aud|set\s*[12ivx]+|encore|disc\s*\d|"
    r"^\s*(the\s+)?\w+\s+(theater|theatre|arena|hall|club|room|ballroom|amphitheat)\w*)",
    re.I,
)
# "01. Bertha", "1) Bertha", "t01 Bertha" -> "Bertha"
_LEADING_NUM = re.compile(r"^\s*[\[\(]?\d{1,2}[\]\).:\-]?\s+")


def _setlist_from_description(desc: str, n_tracks: int) -> list[str]:
    if not desc or n_tracks <= 0:
        return []
    text = _HTML.sub("\n", desc)
    text = text.replace("&amp;", "&").replace("&gt;", ">").replace("&nbsp;", " ")
    songs = []
    for raw in text.splitlines():
        line = _LEADING_NUM.sub("", raw.strip(" \t.-–—*"))
        if not line or len(line) > 90 or _NOT_A_SONG.match(line):
            continue
        songs.append(line)
    # Only believe it if it lines up with the actual files — a mismatched setlist
    # is worse than an honest "Track 3", because it silently mislabels the music.
    return songs if len(songs) == n_tracks else []


def _title_for(f: dict, name: str, setlist: list[str], i: int) -> str:
    title = (f.get("title") or "").strip()
    if title:
        return title
    if setlist:
        return setlist[i]
    stem = re.sub(r"\.[^.]+$", "", name)
    # a stem that is just the identifier + track number carries no information
    if re.fullmatch(r"[a-z0-9._-]*?[dt]?\d{1,3}", stem, re.I) or not re.search(r"[a-z]{3}", stem, re.I):
        return f"Track {i + 1}"
    return stem


def get_show(identifier: str) -> dict:
    r = client().get(f"{BASE}/metadata/{identifier}")
    r.raise_for_status()
    js = r.json()
    meta = js.get("metadata", {})
    files = js.get("files", [])

    mp3s = [f for f in files if "mp3" in str(f.get("format", "")).lower()
            or str(f.get("name", "")).lower().endswith(".mp3")]
    # Prefer VBR MP3 derivatives when both exist
    vbr = [f for f in mp3s if "vbr" in str(f.get("format", "")).lower()]
    chosen = vbr or mp3s
    chosen.sort(key=_track_sort_key)

    setlist = _setlist_from_description(meta.get("description", ""), len(chosen))

    tracks = []
    for i, f in enumerate(chosen):
        name = f.get("name", "")
        tracks.append({
            "name": name,
            "title": _title_for(f, name, setlist, i),
            "length": f.get("length", ""),
            "url": f"{BASE}/download/{identifier}/{urllib.parse.quote(name)}",
        })
    return {
        "identifier": identifier,
        "title": meta.get("title", identifier),
        "date": meta.get("date", ""),
        "venue": meta.get("venue", ""),
        "creator": meta.get("creator", ""),
        "avg_rating": js.get("reviews_avg", None),
        "tracks": tracks,
    }


def pick_show(cfg: dict, exclude_ids: set[str]) -> dict | None:
    """Pick a (weighted-random, well-rated) show matching a channel's config."""
    docs = search_shows(
        collections=cfg.get("collections"),
        free_text=cfg.get("free_text"),
        year=cfg.get("year"),
        min_rating=cfg.get("min_rating"),
        rows=int(cfg.get("rows", 50)),
        sort=cfg.get("sort", "avg_rating desc"),
    )
    candidates = [d for d in docs if d.get("identifier") not in exclude_ids]
    if not candidates:
        candidates = docs  # all seen recently: allow repeats rather than silence
    if not candidates:
        return None
    top = candidates[: min(15, len(candidates))]
    doc = random.choice(top)
    return get_show(doc["identifier"])
