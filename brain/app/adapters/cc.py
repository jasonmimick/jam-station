"""Source adapter for Creative-Commons / public-domain audio on archive.org.

WHY THIS EXISTS, AND WHY IT IS NOT JUST "the archive adapter without the etree filter":

The `archive` adapter is pinned to `mediatype:etree` — the Live Music Archive, which is
taper-friendly LIVE recordings that the bands explicitly permit. That's the only reason
jam-station is legally clean. It also means the DJ can't play ragtime, or Danish folk, or
anything that isn't a jam band with a taping policy.

The rest of archive.org is *not* uniformly safe. The ragtime you'd reach for lives in the
78rpm collections — the Great 78 Project — which is the exact content the major labels sued
the Internet Archive over ($621M, settled 2025). Publicly REBROADCASTING that is a worse
position than merely hosting it. So this adapter refuses to touch those collections at all,
by name, rather than trusting a query to stay away from them.

What it does instead: it requires an explicit `licenseurl` on every item. That's the
machine-checkable version of "clean content" — the artist (or the public domain) has said,
in metadata, that this may be shared. Creative Commons and CC0/public-domain marks qualify.
Nothing without a license does.

⚠️  LICENCE VARIANTS MATTER, AND THEY ARE A BUSINESS LANDMINE.
    ~25% of CC audio is NON-COMMERCIAL only (by-nc, by-nc-sa, by-nc-nd). That is fine for a
    personal station and BREAKS THE DAY THERE IS MONEY (paid relays, hosted nodes,
    subdomains). So we record the licence on every queued track — `commercial_ok` says
    whether it survives a commercial tier. Filtering later is then a WHERE clause instead of
    a re-crawl. Cheap now, horrible to retrofit.
"""
from __future__ import annotations

import random
import re
import urllib.parse

import httpx

from . import archive

BASE = "https://archive.org"

# Collections we will not touch. The 78rpm/Great-78 family is the litigated content; the
# rest are audio but not music (spoken word, radio, audiobooks) and would poison a station.
BLOCKED = (
    "78rpm", "georgeblood",                      # the Great 78 Project — see the docstring
    "librivox", "audio_bookspoetry",             # audiobooks
    "podcasts", "radioprograms", "oldtimeradio", "radiostationarchives",
    "audio_news", "audio_religion",
)

# A licence that permits commercial use. NC = non-commercial only.
_NC = re.compile(r"/(by-nc|nc)[-/]", re.I)


def _client() -> httpx.Client:
    return httpx.Client(timeout=20, follow_redirects=True,
                        headers={"user-agent": "jam-station/1.0"})


def commercial_ok(licenseurl: str) -> bool:
    """False for any NonCommercial licence. See the landmine note above."""
    return bool(licenseurl) and not _NC.search(licenseurl)


# Restrict to MUSIC collections. Without this, a free-text search for "danish folk"
# returns Danish *audiobooks* — Poe read aloud, fairy tales, "Eskimo Folk-Tales" — because
# archive.org's audio is mostly spoken word by volume. This one clause is the difference
# between a ragtime station and a station that reads you a story.
MUSIC = "collection:(audio_music OR netlabels)"


def build_query(search: str | None, year: int | None = None) -> str:
    parts = [
        "mediatype:(audio)",
        "licenseurl:[* TO *]",          # THE rule: an explicit licence, or we don't play it
        MUSIC,                          # ...and it has to actually be music
    ]
    if search:
        parts.append(f"({search})")     # free text — "ragtime", "danish folk", a vibe
    if year:
        parts.append(f"year:({year})")
    for c in BLOCKED:
        parts.append(f"-collection:({c})")
    return " AND ".join(parts)


def search_items(search: str | None = None, year: int | None = None,
                 rows: int = 60, sort: str = "downloads desc") -> list[dict]:
    """Find CC/public-domain audio items. `sort` defaults to downloads — with no community
    ratings out here (that's an etree thing), popularity is the only quality signal we get."""
    params = {
        "q": build_query(search, year),
        "fl[]": ["identifier", "title", "creator", "year", "licenseurl", "downloads"],
        "rows": rows, "page": 1, "output": "json", "sort[]": sort,
    }
    with _client() as c:
        r = c.get(f"{BASE}/advancedsearch.php", params=params)
        r.raise_for_status()
    return r.json().get("response", {}).get("docs", [])


def get_show(identifier: str) -> dict:
    """Reuse the archive adapter's file handling — same metadata endpoint, same MP3
    derivative logic, same honest title fallback ('Track 3' beats a filename)."""
    show = archive.get_show(identifier)
    with _client() as c:
        meta = c.get(f"{BASE}/metadata/{identifier}").json().get("metadata", {})
    lic = str(meta.get("licenseurl") or "")
    show["licenseurl"] = lic
    show["commercial_ok"] = commercial_ok(lic)
    return show


def pick_show(cfg: dict, exclude_ids: set[str]) -> dict | None:
    """Pick an item for this channel.

    TWO MODES, and the first is the good one:

    `items`  — a CURATED list of archive identifiers that a human (or the DJ) has actually
               looked at and judged. Play only from these.
    `search` — free text. Convenient, and QUALITY IS NOT GUARANTEED: a search for "ragtime"
               happily returns "Mystified - Elemental Ragtime", an ambient noise album whose
               only ragtime is the word in its title. Matching a word is not matching a
               genre. Use search to FIND candidates; use `items` to SHIP them.
    """
    curated = cfg.get("items") or []
    if curated:
        pool = [i for i in curated if i not in exclude_ids] or list(curated)
        random.shuffle(pool)
        for ident in pool[:8]:
            try:
                show = get_show(ident)
            except Exception:
                continue
            if show.get("tracks"):
                return show
        return None

    docs = search_items(
        search=cfg.get("search") or cfg.get("free_text"),
        year=cfg.get("year"),
        rows=int(cfg.get("rows", 60)),
        sort=cfg.get("sort", "downloads desc"),
    )
    if cfg.get("commercial_only"):                 # for a future paid tier
        docs = [d for d in docs if commercial_ok(str(d.get("licenseurl") or ""))]

    candidates = [d for d in docs if d.get("identifier") not in exclude_ids] or docs
    if not candidates:
        return None

    # Weight toward the popular half — out here popularity is the only quality signal, and a
    # random CC upload is as likely to be a phone recording of a lawnmower as it is music.
    top = candidates[: max(1, len(candidates) // 2)]
    random.shuffle(top)

    for doc in top[:8]:                            # some items are art, text, or empty
        try:
            show = get_show(doc["identifier"])
        except Exception:
            continue
        if show.get("tracks"):
            show["creator"] = show.get("creator") or doc.get("creator") or ""
            return show
    return None
