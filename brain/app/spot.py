"""Spot: snap a photo of music in the wild, and the station identifies it.

You hear something — on a car radio, a café playlist, a friend's turntable, a gig poster — and
you take a picture to remember it. Send that photo here and Claude reads whatever's in the frame
(a now-playing screen, an album cover, a marquee) and pulls out artist + title. Then two things,
in order:

  1. DO YOU OWN IT?  We match the ID against your ripped catalog. Hit -> it's playable, right now.
  2. YOU DON'T?      We enrich it (MusicBrainz year + a real cover) and save it to your Spotted
                     shelf with links out (YouTube Music / Discogs) so you can hear it elsewhere
                     or know to grab the CD. We can identify and remember it; we can't stream
                     what isn't ours.

Every spot is kept: the photo, what Claude saw, and where it landed. The photo lives in the music
volume under .spots/ (hidden from the catalog walk), so it serves through the same members-only
/music origin as the records.
"""
from __future__ import annotations

import base64
import json
import os
import re
from urllib.parse import quote

import anthropic

from . import config, covers, db
from .adapters import library

SPOTS_DIR = os.path.join(config.MUSIC_DIR, ".spots")

_PROMPT = """This is a photo someone took to REMEMBER a piece of music they encountered in the
wild — so they can find it and listen later. It might be: a car stereo or radio display showing
track text, a phone screen with Spotify/Apple Music/Shazam open, an album cover or CD, a vinyl
sleeve or label, a gig poster or club marquee, a handwritten note.

Read everything legible and identify the music. Prefer what's actually shown, but you may use
your knowledge to complete an obvious partial (a cover you recognize, a truncated title). Give:
- artist and title of the SONG if there is one; album if shown or known.
- If it's plainly an album/cover with no single song, set title empty and fill album.
- confidence: "high" only when the text/cover is unambiguous, else "medium" or "low".
- saw: one short phrase naming what the photo actually is ("car stereo display", "album cover").
- is_music: false only if there's genuinely no identifiable music in the frame."""

_TOOL = {
    "name": "identified",
    "description": "Report the music identified in the photo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_music": {"type": "boolean"},
            "artist": {"type": "string"},
            "title": {"type": "string"},
            "album": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "saw": {"type": "string"},
        },
        "required": ["is_music", "artist", "title", "album", "confidence", "saw"],
    },
}


def identify(image_bytes: bytes, media_type: str) -> dict:
    """One Claude vision call, forced through the `identified` tool so we always get structured
    fields back (never prose to parse)."""
    b64 = base64.standard_b64encode(image_bytes).decode()
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=500,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "identified"},
        messages=[{"role": "user", "content": [
            {"type": "image",
             "source": {"type": "base64", "media_type": media_type, "data": b64}},
            {"type": "text", "text": _PROMPT},
        ]}],
    )
    for block in msg.content:
        if block.type == "tool_use":
            return block.input
    return {"is_music": False, "artist": "", "title": "", "album": "",
            "confidence": "low", "saw": "couldn't read the photo"}


_WORD = re.compile(r"[a-z0-9]+")


def _norm(s: str) -> list[str]:
    return _WORD.findall((s or "").lower())


def _overlap(a: str, b: str) -> bool:
    """Loose token match — one side's words are (mostly) a subset of the other's. Catches
    'The Beatles' vs 'Beatles' and 'Miles Davis Quintet' vs 'Miles Davis' without a fuzzy lib."""
    sa, sb = set(_norm(a)), set(_norm(b))
    if not sa or not sb:
        return False
    small, big = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    return len(small & big) >= max(1, len(small) - 1)


def match_library(artist: str, title: str, album: str) -> dict | None:
    """Path 1: is this in the crate? Match the identified artist to an album's artist, then try
    to land the exact track by title. Artist-only (right record, song not pinned) still counts —
    it opens the album."""
    best = None
    for alb in library.list_albums():
        if not (_overlap(artist, alb["artist"]) or _overlap(album, alb["album"])):
            continue
        if title:
            for i, tr in enumerate(library.album_tracks(alb["dir"])):
                if _overlap(title, tr["title"]):
                    return {"dir": alb["dir"], "album": alb["album"], "artist": alb["artist"],
                            "track": tr["title"], "url": tr["url"], "index": i}
        best = best or {"dir": alb["dir"], "album": alb["album"], "artist": alb["artist"],
                        "track": "", "url": "", "index": -1}
    return best


def _links(artist: str, title: str, album: str, mbid: str) -> dict:
    q = " ".join(x for x in (artist, title or album) if x).strip()
    out = {
        "youtube": "https://music.youtube.com/search?q=" + quote(q),
        "discogs": "https://www.discogs.com/search/?type=release&q="
                   + quote(" ".join(x for x in (artist, album or title) if x).strip()),
    }
    out["musicbrainz"] = ("https://musicbrainz.org/release/" + mbid if mbid
                          else "https://musicbrainz.org/search?type=release&query=" + quote(q))
    return out


def create_spot(image_bytes: bytes, media_type: str, email: str) -> dict:
    os.makedirs(SPOTS_DIR, exist_ok=True)
    ident = identify(image_bytes, media_type)
    artist = (ident.get("artist") or "").strip()
    title = (ident.get("title") or "").strip()
    album = (ident.get("album") or "").strip()

    status, matched, mbid, year, cover_url = "unknown", None, "", "", ""
    links = {}
    if ident.get("is_music") and (artist or title or album):
        matched = match_library(artist, title, album)
        if matched:
            status = "matched"
        else:
            status = "wishlist"
            hit = covers._search_release(artist, album or title) or {}
            mbid, year = hit.get("mbid") or "", hit.get("year") or ""
            links = _links(artist, title, album, mbid)

    row = db.query(
        "INSERT INTO spots(email, status, artist, title, album, year, confidence, saw, mbid, "
        "matched_dir, matched_url, links) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id",
        (email, status, artist, title, album, year, ident.get("confidence", ""),
         ident.get("saw", ""), mbid, (matched or {}).get("dir", ""),
         (matched or {}).get("url", ""), json.dumps(links)))
    sid = row[0]["id"]

    ext = "png" if "png" in media_type else "jpg"
    fname = f"{sid}.{ext}"
    with open(os.path.join(SPOTS_DIR, fname), "wb") as f:
        f.write(image_bytes)
    img_url = "/music/" + quote(".spots/" + fname)
    db.execute("UPDATE spots SET image_path=? WHERE id=?", (img_url, sid))

    # fetch the real cover for a wishlist hit, so the shelf shows the sleeve next to the snapshot
    if mbid:
        cover_file = os.path.join(SPOTS_DIR, f"{sid}_cover.jpg")
        if covers._fetch_cover(mbid, cover_file):
            cover_url = "/music/" + quote(f".spots/{sid}_cover.jpg")
            db.execute("UPDATE spots SET cover_url=? WHERE id=?", (cover_url, sid))

    return get_spot(sid)


def _shape(r: dict) -> dict:
    r = dict(r)
    try:
        r["links"] = json.loads(r.get("links") or "{}")
    except Exception:
        r["links"] = {}
    return r


def get_spot(sid: int) -> dict | None:
    rows = db.query("SELECT * FROM spots WHERE id=?", (sid,))
    return _shape(rows[0]) if rows else None


def list_spots(limit: int = 100) -> list[dict]:
    return [_shape(r) for r in db.query(
        "SELECT * FROM spots ORDER BY id DESC LIMIT ?", (limit,))]


def delete_spot(sid: int) -> None:
    row = db.query("SELECT image_path, cover_url FROM spots WHERE id=?", (sid,))
    db.execute("DELETE FROM spots WHERE id=?", (sid,))
    for url in (row and (row[0]["image_path"], row[0]["cover_url"]) or ()):
        if url:
            p = os.path.join(config.MUSIC_DIR, url[len("/music/"):])
            try:
                os.remove(os.path.realpath(p))
            except OSError:
                pass
