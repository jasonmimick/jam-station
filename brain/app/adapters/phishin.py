"""Source adapter for phish.in — Phish live shows (the band keeps them off the Archive).

v2 API, no key needed. Two endpoints do everything:
  - /api/v2/shows          : find shows (community likes_count is the quality signal)
  - /api/v2/shows/<date>   : one show's tracklist, each track with a direct mp3_url
Show identifiers are dates (YYYY-MM-DD) — one show per date.
"""
from __future__ import annotations

import random

import httpx

BASE = "https://phish.in/api/v2"
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


def search_shows(year=None, rows=40, sort="likes_count:desc") -> list[dict]:
    params = {
        "per_page": str(rows),
        "sort": sort,
        "audio_status": "complete",
    }
    if year:
        params["year"] = str(year)
    r = client().get(f"{BASE}/shows", params=params)
    r.raise_for_status()
    shows = r.json().get("shows", [])
    return [{
        "identifier": s["date"],
        "date": s["date"],
        "venue": s.get("venue_name", ""),
        "location": (s.get("venue") or {}).get("location", ""),
        "tour": s.get("tour_name", ""),
        "likes_count": s.get("likes_count", 0),
        "duration_min": round((s.get("duration") or 0) / 60000),
    } for s in shows]


def get_show(date: str) -> dict:
    r = client().get(f"{BASE}/shows/{date}")
    r.raise_for_status()
    js = r.json()
    tracks = []
    for t in sorted(js.get("tracks", []), key=lambda t: t.get("position", 0)):
        if not t.get("mp3_url"):
            continue
        tracks.append({
            "name": t.get("slug", ""),
            "title": t.get("title", ""),
            "length": str(round((t.get("duration") or 0) / 1000)),
            "url": t["mp3_url"],
        })
    venue = js.get("venue_name", "")
    when = js.get("date", date)
    return {
        "identifier": when,
        "title": f"Phish Live at {venue} on {when}" if venue else f"Phish {when}",
        "date": when,
        "venue": venue,
        "creator": "Phish",
        "likes_count": js.get("likes_count", 0),
        "tracks": tracks,
    }


def pick_show(cfg: dict, exclude_ids: set[str]) -> dict | None:
    """Pick a (weighted-random, well-liked) show matching a channel's config."""
    docs = search_shows(
        year=cfg.get("year"),
        rows=int(cfg.get("rows", 50)),
        sort=cfg.get("sort", "likes_count:desc"),
    )
    candidates = [d for d in docs if d["identifier"] not in exclude_ids]
    if not candidates:
        candidates = docs  # all seen recently: allow repeats rather than silence
    if not candidates:
        return None
    top = candidates[: min(15, len(candidates))]
    doc = random.choice(top)
    return get_show(doc["identifier"])
