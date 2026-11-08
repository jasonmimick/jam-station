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
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config

_GENERIC = re.compile(r"^(\d{1,2})[ .\-_]+audio track$", re.I)   # "01 Audio Track" — an un-named rip
_NUMPREFIX = re.compile(r"^(\d{1,2})[ .\-_]+")

UA = "jam-station/1.0 (https://jam-station.runslab.run)"
_lock = threading.Lock()
log = logging.getLogger("jam.covers")


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


def _names(entity: dict) -> list[str]:
    """genre + tag names off any MB entity, tags sorted by vote count."""
    names = [g.get("name", "") for g in (entity.get("genres") or [])]
    names += [t.get("name", "") for t in sorted(
        entity.get("tags") or [], key=lambda t: -(t.get("count") or 0))]
    return names


def _genres(mbid: str) -> list[str]:
    """Genres for a release, bucketized — falling back UP the MB data model.
    Releases are rarely tagged directly; the release-group usually is, and the
    ARTIST almost always is (a Miles Davis record is jazz because Miles is)."""
    try:
        data = json.load(_get(
            f"https://musicbrainz.org/ws/2/release/{mbid}"
            "?inc=genres+tags+release-groups+artist-credits&fmt=json"))
    except Exception:
        return []
    out = bucketize(_names(data))
    if out:
        return out
    out = bucketize(_names(data.get("release-group") or {}))
    if out:
        return out
    names: list[str] = []
    for ac in data.get("artist-credit") or []:
        names += _names(ac.get("artist") or {})
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
    # a cover in hand, or every source tried (art_v2 = the careful find_cover pass, 2026-11)
    cover_done = os.path.exists(cover_p) or (meta.get("itunes") and meta.get("art_v2"))
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
    if not os.path.exists(cover_p) and not meta.get("art_v2"):
        # the first lookups take MB's top hit and iTunes' first result; this one searches
        # release groups and only accepts a clear artist + album match (see find_cover)
        if find_cover(artist, album, cover_p) is not None:
            meta["art_v2"] = True
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
    try:
        from . import channels                 # late import — no cycle at module load
        channels.sync_genre_channels()         # fresh genres may birth a station
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


# ── careful cover lookup: Cover Art Archive (via MusicBrainz), then iTunes ──────
# The names come from folder names, so a loose "first search result" lookup hands a
# Pearl Jam bootleg some other record's sleeve. find_cover() only accepts a candidate
# whose artist AND album both agree with ours once case, punctuation, accents, a
# leading "The" and edition tails ("[Bonus Tracks]", "(Remastered)", "Disc 2") are
# set aside. No clear match = no cover; the generated tile is better than a wrong one.

_VARIOUS = {"various artists", "various", "va", "soundtrack", "soundtracks", "original soundtrack"}
_SKIP_ALBUM = re.compile(r"^(unknown album|loose tracks|untitled)\b", re.I)
_mb_lock = threading.Lock()
_mb_last = [0.0]
_it_lock = threading.Lock()
_it_last = [0.0]


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("+", " and ")
    s = re.sub(r"[\'\u2019.`]", "", s)               # P.O.D. -> pod, Y'All -> yall
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"^the ", "", s)


def _album_key(s: str) -> str:
    """The album's name without edition tails: brackets/parens and 'Disc 2' / 'CD 1'."""
    # a "[Box Set]" is its own release, never the album that shares its name
    s = re.sub(r"[\[(]([^\])]*)[\])]",
               lambda m: f" {m.group(1)} " if re.search(r"\bbox", m.group(1), re.I) else " ", s or "")
    s = re.sub(r"\b(disc|cd)\s*\d+\b", " ", s, flags=re.I)
    return _norm(s)


def _artist_key(s: str) -> str:
    s = re.split(r"\s+(feat\.?|featuring|ft\.)\s+", s or "", flags=re.I)[0]
    return _norm(s)


def _is_various(artist: str) -> bool:
    return _norm(artist) in _VARIOUS


def same_artist(ours: str, theirs: str) -> bool:
    if _is_various(ours):
        return _is_various(theirs)
    a, b = _artist_key(ours).replace(" ", ""), _artist_key(theirs).replace(" ", "")
    return bool(a) and a == b


def same_album(ours: str, theirs: str) -> bool:
    # spaces don't count either ("Hotdog" / "Hot Dog"); words and their order do
    a, b = _album_key(ours).replace(" ", ""), _album_key(theirs).replace(" ", "")
    return bool(a) and (a == b or a == _norm(theirs).replace(" ", "")
                        or _norm(ours).replace(" ", "") == b)


def lookable(artist: str, album: str) -> bool:
    """Worth asking about at all: a real artist and a real album name."""
    a = _norm(artist)
    if not a or a.startswith("unknown") or not _album_key(album):
        return False
    return not _SKIP_ALBUM.match((album or "").strip())


def _polite(lock, last, gap: float) -> None:
    with lock:
        wait = last[0] + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        last[0] = time.time()


class _Busy(Exception):
    """The service said slow down (or was unreachable): try again later, don't record a miss."""


def _get_json(url: str, lock, last, gap: float):
    _polite(lock, last, gap)
    try:
        return json.load(_get(url))
    except urllib.error.HTTPError as e:
        if e.code in (403, 429, 503):
            raise _Busy(str(e))
        return {}
    except Exception as e:                          # network trouble
        raise _Busy(str(e))


def _save(url: str, dest: str) -> bool:
    if os.path.exists(dest):                         # never overwrite a sleeve already there
        return True
    try:
        data = _get(url, timeout=30).read()
    except Exception:
        return False
    if not data or len(data) < 1500:                 # a stray error page, not a picture
        return False
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    if os.path.exists(dest):
        os.unlink(tmp)
        return True
    os.replace(tmp, dest)
    return True


def _mb_cover(artist: str, album: str, dest: str) -> bool:
    title = re.sub(r"\s*[\[(][^\])]*[\])]", "", album).strip() or album
    title = re.sub(r"\s*\b(disc|cd)\s*\d+\b\s*$", "", title, flags=re.I).strip() or title
    q = f'releasegroup:"{title}"'
    if not _is_various(artist):
        q += f' AND artist:"{_artist_key(artist) or artist}"'
    url = "https://musicbrainz.org/ws/2/release-group/?" + urllib.parse.urlencode(
        {"query": q, "fmt": "json", "limit": "10"})
    data = _get_json(url, _mb_lock, _mb_last, 1.1)  # MusicBrainz asks for 1 request a second
    for rg in data.get("release-groups") or []:
        credit = "".join((c.get("name") or (c.get("artist") or {}).get("name") or "")
                         + (c.get("joinphrase") or "") for c in rg.get("artist-credit") or [])
        if not (same_album(album, rg.get("title", "")) and same_artist(artist, credit)):
            continue
        for size in ("front-500", "front"):
            if _save(f"https://coverartarchive.org/release-group/{rg['id']}/{size}", dest):
                return True
    return False


def _itunes_match(artist: str, album: str, dest: str) -> bool:
    term = f"{'' if _is_various(artist) else _artist_key(artist)} {_album_key(album)}".strip()
    url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": term, "entity": "album", "limit": "15"})
    data = _get_json(url, _it_lock, _it_last, 3.0)   # iTunes allows ~20 searches a minute
    for r in data.get("results") or []:
        if not (same_album(album, r.get("collectionName", ""))
                and same_artist(artist, r.get("artistName", ""))):
            continue
        art = r.get("artworkUrl100") or ""
        if art and _save(art.replace("100x100bb", "600x600bb"), dest):
            return True
    return False


def find_cover(artist: str, album: str, dest: str):
    """The real sleeve for artist+album, saved at dest. True = found (or already there),
    False = both sources asked and neither has a clear match, None = a source was busy or
    unreachable, so ask again later. Never overwrites an existing file."""
    if os.path.exists(dest):
        return True
    if not lookable(artist, album):
        return False
    busy = False
    for source in (_mb_cover, _itunes_match):
        try:
            if source(artist, album, dest):
                return True
        except _Busy:
            busy = True
    return None if busy else False


# ── attic sleeves: cached on the brain's data volume ─────────────────────────
# The vault is a Time Capsule that keeps raw rescued files, so nothing is written there:
# sleeves live in DATA_DIR/attic-art (a docker volume on the mini's own disk, survives
# redeploys; /cache did not). A miss is a <slug>.jpg.none marker, retried after MISS_DAYS.

MISS_DAYS = 30


def attic_art_path(artist: str, album: str) -> str:
    """Where a vault album's sleeve lives (or would live) in the cache. One slug rule,
    shared by the lazy endpoint, the albums-list enrichment, and the warmer."""
    slug = re.sub(r"[^a-z0-9]+", "-", f"{artist} {album}".lower()).strip("-")[:80]
    return os.path.join(config.ATTIC_ART_DIR, slug + ".jpg") if slug else ""


def missed_recently(dest: str) -> bool:
    try:
        return time.time() - os.path.getmtime(dest + ".none") < MISS_DAYS * 86400
    except OSError:
        return False


def attic_lookup(artist: str, album: str, dest: str):
    """find_cover for one vault album, recording a miss so it isn't asked again soon.
    Returns find_cover's True / False / None."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    got = find_cover(artist, album, dest)
    if got and os.path.exists(dest + ".none"):
        os.unlink(dest + ".none")
    if got is False:
        open(dest + ".none", "w").close()
    return got


_attic_lock = threading.Lock()
WARM_ATTIC = True     # tests flip this off so lifespans can't spawn real lookups
attic_progress = {"running": False, "checked": 0, "found": 0, "missed": 0, "busy": 0, "total": 0}


def kick_attic() -> None:
    """Fill the vault's sleeves in the background: MusicBrainz at 1 request a second,
    iTunes at one search every 3 seconds. Skips everything cached or recently missed,
    so a re-run after a redeploy or on a later albums request costs seconds."""
    if not WARM_ATTIC or not _attic_lock.acquire(blocking=False):
        return
    def run():
        try:
            from .adapters import attic
            albums = attic.list_albums()
            attic_progress.update(running=True, checked=0, found=0, missed=0, busy=0,
                                  total=len(albums), started=time.time())
            for al in albums:
                attic_progress["checked"] += 1
                if attic_progress["checked"] % 50 == 0:
                    log.info("attic covers: %s", attic_progress)
                dest = attic_art_path(al.get("artist", ""), al.get("album", ""))
                if not dest or os.path.exists(dest) or missed_recently(dest):
                    continue
                try:
                    got = attic_lookup(al.get("artist", ""), al.get("album", ""), dest)
                    if got:
                        attic_progress["found"] += 1
                    elif got is False:
                        attic_progress["missed"] += 1
                    else:
                        attic_progress["busy"] += 1
                        time.sleep(30)               # a source pushed back; give it room
                except Exception:
                    pass
        finally:
            attic_progress.update(running=False, finished=time.time())
            log.info("attic covers pass done: %s", attic_progress)
            _attic_lock.release()
    threading.Thread(target=run, daemon=True).start()
