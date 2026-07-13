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

    tracks = []
    for f in chosen:
        name = f.get("name", "")
        tracks.append({
            "name": name,
            "title": f.get("title") or re.sub(r"\.[^.]+$", "", name),
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
