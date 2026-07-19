"""Album enrichment: real cover art + year, from MusicBrainz and the Cover Art Archive.

The ripper gets the audio in; this fills in what makes a record feel like a record — the sleeve
and the year. It runs in the BRAIN (not the ripper) so it enriches on its own schedule and
backfills albums that were ripped before this existed: for each cds/<album> folder we search
MusicBrainz by artist+album, take the release id + date, and pull the front cover. Results are
cached next to the tracks as _album.json + _cover.jpg, so it's a one-time cost per album.

Runs on a background thread, rate-limited (MusicBrainz asks ~1 req/sec). Best-effort — no art
found, or MB down, just means the UI shows the generated tile. Never blocks a request.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from . import config

_GENERIC = re.compile(r"^(\d{1,2})[ .\-_]+audio track$", re.I)   # "01 Audio Track" — an un-named rip
_NUMPREFIX = re.compile(r"^(\d{1,2})[ .\-_]+")

UA = "jam-station/1.0 (https://jam-station.runslab.run)"
_lock = threading.Lock()


def _get(url: str, timeout: int = 20):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": UA}), timeout=timeout)


def _clean_album(album: str) -> str:
    """Drop disc-number tails a rip picks up from the disc's volume name — '[Disc 1]', '(disc 2)',
    'Disc 1' — so the title matches what MusicBrainz actually indexes."""
    a = re.sub(r"\s*[\[(]?\bdisc\s*\d+\b[\])]?\s*$", "", album, flags=re.I)
    return a.strip(" -") or album


def _search_release(artist: str, album: str) -> dict | None:
    album = _clean_album(album)
    q = f'release:"{album}"'
    if artist and "unknown" not in artist.lower():
        q += f' AND artist:"{artist}"'
    url = "https://musicbrainz.org/ws/2/release/?" + urllib.parse.urlencode(
        {"query": q, "fmt": "json", "limit": "1"})
    try:
        rels = json.load(_get(url)).get("releases") or []
    except Exception:
        return None
    if not rels:
        return None
    r = rels[0]
    return {"mbid": r.get("id"), "year": (r.get("date") or "")[:4]}


# ── genres: coarse, owner-curated buckets ────────────────────────────────
# MusicBrainz speaks in dozens of fine-grained tags; the shelf speaks in a
# record-store's worth of sections. Tags map DOWN into buckets here; the owner
# can overwrite any album's genres (any label at all) via /api/library/genre,
# and an owner-set value is never touched again (genres_owner in _album.json).
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
    """Fine tags -> coarse shelf sections, order of first match, deduped."""
    out = []
    for tag in tags:
        t = (tag or "").lower()
        for bucket, needles in BUCKETS:
            if any(n in t for n in needles) and bucket not in out:
                out.append(bucket)
    return out[:3]                                   # a record lives in a few sections, not ten


def _genres(mbid: str) -> list[str]:
    """The release's genre/tag names from MusicBrainz, bucketized. Best-effort."""
    try:
        data = json.load(_get(
            f"https://musicbrainz.org/ws/2/release/{mbid}?inc=genres+tags&fmt=json"))
    except Exception:
        return []
    names = [g.get("name", "") for g in (data.get("genres") or [])]
    names += [t.get("name", "") for t in sorted(
        data.get("tags") or [], key=lambda t: -(t.get("count") or 0))]
    return bucketize(names)


def _fetch_cover(mbid: str, dest: str) -> bool:
    # CAA redirects to the actual image on archive.org; urllib follows it.
    for size in ("front-500", "front"):
        try:
            data = _get(f"https://coverartarchive.org/release/{mbid}/{size}", timeout=30).read()
        except Exception:
            continue
        if data and len(data) > 1500:                 # guard against a stray error page
            tmp = dest + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            return True
    return False


def _itunes_cover(artist: str, album: str, dest: str) -> bool:
    """Fallback when the Cover Art Archive has nothing. The iTunes Search API is free, keyless, and
    has artwork for nearly every commercial album — you just ask for a bigger size than it returns."""
    term = f"{artist} {album}".strip()
    if not term:
        return False
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": term, "entity": "album", "limit": "3"})
    try:
        results = json.load(_get(url)).get("results") or []
    except Exception:
        return False
    for r in results:
        art = r.get("artworkUrl100") or r.get("artworkUrl60") or ""
        if not art:
            continue
        big = art.replace("100x100bb", "600x600bb").replace("60x60bb", "600x600bb")
        try:
            data = _get(big, timeout=30).read()
        except Exception:
            continue
        if data and len(data) > 1500:
            tmp = dest + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            return True
    return False


def _has_generic(folder: str) -> bool:
    try:
        return any(_GENERIC.match(os.path.splitext(f)[0])
                   for f in os.listdir(folder) if f.lower().endswith(".mp3"))
    except Exception:
        return False


def _tracklist(mbid: str, folder: str) -> dict:
    """{position: title} from the release's recordings — the real song names MusicBrainz has
    even when macOS labelled every track 'Audio Track'.

    Multi-disc releases repeat positions 1..N on EVERY medium, and 'first medium wins' once
    named an entire disc 2 with disc 1's songs. So when there's more than one medium, pick
    the one whose track lengths actually line up with the files on disk (256k CBR makes a
    file's duration size*8/256000 to ~0.1s). No medium fits the file count -> first medium,
    the old behaviour."""
    try:
        data = json.load(_get(f"https://musicbrainz.org/ws/2/release/{mbid}?inc=recordings&fmt=json"))
    except Exception:
        return {}
    media = data.get("media") or []
    if len(media) > 1:
        durs = [os.path.getsize(os.path.join(folder, f)) * 8 / 256000
                for f in sorted(os.listdir(folder)) if f.lower().endswith(".mp3")]

        def misfit(m: dict) -> float:
            lens = [(t.get("length") or 0) / 1000 for t in m.get("tracks", [])]
            if len(lens) != len(durs) or not all(lens):
                return float("inf")
            return sum(abs(a - b) for a, b in zip(lens, durs))

        best = min(media, key=misfit)
        media = [best] if misfit(best) != float("inf") else media[:1]
    titles = {}
    for medium in media:
        for t in medium.get("tracks", []):
            try:
                pos = int(t.get("position") or t.get("number"))
            except (TypeError, ValueError):
                continue
            title = t.get("title") or (t.get("recording") or {}).get("title")
            if pos and title and pos not in titles:
                titles[pos] = title
    return titles


def _retitle(folder: str, titles: dict) -> None:
    for f in os.listdir(folder):
        if not f.lower().endswith(".mp3"):
            continue
        m = _GENERIC.match(os.path.splitext(f)[0])         # only rename generic "NN Audio Track"
        if not m:
            continue
        title = titles.get(int(m.group(1)))
        if not title:
            continue
        safe = re.sub(r'[/\\:*?"<>|]', "-", title).strip()
        newname = f"{m.group(1)} {safe}.mp3"
        if newname != f:
            try:
                os.rename(os.path.join(folder, f), os.path.join(folder, newname))
            except Exception:
                pass


def _enrich_one(folder: str, name: str) -> None:
    meta_p = os.path.join(folder, "_album.json")
    cover_p = os.path.join(folder, "_cover.jpg")
    # Folder mtime IS "date added" in the gallery — enrichment writing art/renaming tracks
    # must not bump a week-old album to the top of "recently added". Save it, restore it.
    try:
        folder_mtime = os.stat(folder).st_mtime
    except OSError:
        folder_mtime = None
    try:
        meta = json.load(open(meta_p)) if os.path.exists(meta_p) else {}
    except Exception:
        meta = {}
    # skip only when nothing's left to do: cover in hand (or unmatchable), no generic
    # titles, AND genres resolved (the key existing at all counts — [] means "asked, none")
    cover_done = os.path.exists(cover_p) or meta.get("itunes")   # a cover in hand, or both sources tried
    if meta.get("tried") and cover_done and not _has_generic(folder) and "genres" in meta:
        return

    artist, album = meta.get("artist"), meta.get("album")
    if not album:                                     # derive from "Artist - Album" folder name
        artist, _, album = name.partition(" - ") if " - " in name else ("", "", name)
    if not album or "unknown" in album.lower():
        return

    if not meta.get("mbid"):
        hit = _search_release(artist, album) or {}
        time.sleep(1.1)                               # MusicBrainz rate limit
        meta.setdefault("mbid", hit.get("mbid") or "")
        meta.setdefault("year", hit.get("year") or "")
    if meta.get("mbid") and not os.path.exists(cover_p):
        _fetch_cover(meta["mbid"], cover_p)
        time.sleep(0.4)
    if not os.path.exists(cover_p) and not meta.get("itunes"):   # Cover Art Archive missed — try iTunes
        _itunes_cover(artist, album, cover_p)
        meta["itunes"] = True
        time.sleep(0.3)
    if "genres" not in meta:                          # owner-set genres always carry the key
        meta["genres"] = _genres(meta["mbid"]) if meta.get("mbid") else []
        if meta.get("mbid"):
            time.sleep(1.1)                           # MusicBrainz rate limit
    if meta.get("mbid") and _has_generic(folder):     # give the tracks their real names
        titles = _tracklist(meta["mbid"], folder)
        time.sleep(1.1)
        if titles:
            _retitle(folder, titles)

    meta.update({"artist": artist or meta.get("artist", ""), "album": album, "tried": True})
    try:
        with open(meta_p + ".tmp", "w") as f:
            json.dump(meta, f)
        os.replace(meta_p + ".tmp", meta_p)
    except Exception:
        pass
    if folder_mtime is not None:
        try:
            os.utime(folder, (folder_mtime, folder_mtime))
        except OSError:
            pass


def _enrich_all() -> None:
    base = os.path.join(config.MUSIC_DIR, "cds")
    if not os.path.isdir(base):
        return
    for name in sorted(os.listdir(base)):
        folder = os.path.join(base, name)
        if os.path.isdir(folder):
            try:
                _enrich_one(folder, name)
            except Exception:
                pass


def kick() -> None:
    """Fire a background enrichment pass if one isn't already running. Cheap to call often."""
    if _lock.acquire(blocking=False):
        def run():
            try:
                _enrich_all()
            finally:
                _lock.release()
        threading.Thread(target=run, daemon=True).start()
