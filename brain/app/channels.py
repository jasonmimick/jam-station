"""Channel manager: seeded stations, queue top-up, next-track for liquidsoap."""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time

import httpx

log = logging.getLogger("jam.channels")

from . import config, db
from .adapters import archive, attic, cc, library, phishin

# Sources whose channels enqueue whole shows via adapter.pick_show()/get_show().
SHOW_ADAPTERS = {"archive": archive, "phishin": phishin, "cc": cc}
STREAMABLE_SOURCES = ("archive", "phishin", "library", "cc", "attic")
# The owner's own records — never listed or served to anyone but members, never
# tunneled. Derived from the source (see list_channels), NEVER a toggle.
PRIVATE_SOURCES = {"library", "attic"}

# The stations jam-station ships with. THESE LIVE IN CODE ON PURPOSE.
#
# They were originally created by running python against the live container, which meant
# they existed only in one sqlite file: not versioned, not reviewable in a diff, not
# reproducible on another node, and gone the moment the volume was. Runtime state is a bad
# place to keep the product.
#
# Collection ids are exact and unobvious (Goose is "GooseBand"), and every one here was
# verified against the live API before it shipped. The `cc` stations carry a CURATED list of
# identifiers rather than a free-text search, because matching a word is not matching a
# genre — a search for "ragtime" cheerfully returns an ambient noise album called
# "Elemental Ragtime".
#
# ensure_seeded() is INSERT OR IGNORE, so these never clobber a channel the DJ created.
SEED_CHANNELS = [
    {
        "slug": "dead77",
        "name": "Dead '77",
        "description": "Grateful Dead 1977 \u2014 the year everyone argues about, best-rated tapes first.",
        "source": "archive",
        "query": {"collections": ["GratefulDead"], "year": 1977, "min_rating": 4.2},
    },
    {
        "slug": "jam",
        "name": "Jam Bands Live",
        "description": "Umphrey's, moe., Biscuits, Cheese, Panic, Goose \u2014 well-rated live tapes.",
        "source": "archive",
        "query": {"collections": ["UmphreysMcGee", "moe", "DiscoBiscuits", "StringCheeseIncident", "WidespreadPanic", "Goose"], "min_rating": 4.0},
    },
    {
        "slug": "phish",
        "name": "Phish",
        "description": "Phish from phish.in \u2014 the most-liked tapes across every era.",
        "source": "phishin",
        "query": {"sort": "likes_count:desc", "rows": 100},
    },
    {
        "slug": "fusion",
        "name": "70s Fusion",
        "description": "Your own fusion library (drop files in music/fusion/).",
        "source": "library",
        "query": {"folders": ["fusion"]},
    },
    {
        # Points at the whole cds/ folder, not one album — so `rip-cd.sh` is the entire
        # workflow. Put a disc in the drive, run it, and the record is on the air. No
        # station to create, no config to touch. The station grows with the shelf.
        "slug": "disc-changer",
        "name": "The Disc Changer",
        "description": "Everything ripped from the CD drive on the mac-mini. Members only.",
        "source": "library",
        "query": {"folders": ["cds"]},
    },
    {
        "slug": "latenight-jazz",
        "name": "Late Night Jazz",
        "description": "Jam-jazz from the Archive: MMW, Jacob Fred, Garaj Mahal.",
        "source": "archive",
        "query": {"collections": ["MedeskiMartinandWood", "JacobFredJazzOdyssey", "GarajMahal"], "min_rating": 3.5},
    },
    {
        "slug": "bluegrass",
        "name": "Bluegrass",
        "description": "",
        "source": "archive",
        "query": {"collections": ["BelaFleckAndTheFlecktones", "BillyStrings", "DavidGrisman"], "min_rating": 4.0, "sort": "avg_rating desc"},
    },
    {
        "slug": "goose",
        "name": "Goose",
        "description": "Goose live tapes \u2014 best-rated.",
        "source": "archive",
        "query": {"collections": ["GooseBand"], "min_rating": 4.0},
    },
    {
        "slug": "psych60s",
        "name": "Psychedelia '67-'72",
        "description": "Quicksilver, New Riders, Country Joe, early Dead. The acid-test era.",
        "source": "archive",
        "query": {"collections": ["QuicksilverMessengerServiceMusic", "NewRidersofthePurpleSage", "CountryJoeMcDonald"], "min_rating": 3.5},
    },
    {
        "slug": "jerry",
        "name": "Jerry",
        "description": "Jerry Garcia Band + Bob Weir. The side doors of the Dead.",
        "source": "archive",
        "query": {"collections": ["JGB", "BobWeir"], "min_rating": 4.0},
    },
    {
        "slug": "eighties",
        "name": "The '80s Tapes",
        "description": "Widespread, Max Creek, Zero, Aquarium Rescue Unit. Smoky rooms, hot boards.",
        "source": "archive",
        "query": {"collections": ["WidespreadPanic", "MaxCreek", "Zero", "AquariumRescueUnit"], "min_rating": 4.0},
    },
    {
        "slug": "nineties",
        "name": "The '90s",
        "description": "moe., Cheese, Blues Traveler, Leftover Salmon, Ween. The second wave.",
        "source": "archive",
        "query": {"collections": ["moe", "StringCheeseIncident", "BluesTraveler", "LeftoverSalmon", "Ween"], "min_rating": 4.0},
    },
    {
        "slug": "fusion-live",
        "name": "Fusion",
        "description": "Garaj Mahal, Snarky Puppy, TAUK, Jazz Mandolin Project, Flecktones. Jazz-rock, live.",
        "source": "archive",
        "query": {"collections": ["GarajMahal", "SnarkyPuppy", "TAUKband", "JazzMandolinProject", "BelaFleckandtheFlecktones", "Aqueous"], "min_rating": 3.8},
    },
    {
        "slug": "soul-jazz",
        "name": "Soul-Jazz",
        "description": "Soulive, New Mastersounds, Greyboy Allstars, Charlie Hunter. Organ trios and grease.",
        "source": "archive",
        "query": {"collections": ["Soulive", "NewMastersounds", "GreyboyAllstars", "CharlieHunter", "RobertWalters20thCongress", "KarlDensonsTinyUniverse"], "min_rating": 3.8},
    },
    {
        "slug": "funk",
        "name": "Funk",
        "description": "Lettuce, Galactic, Dumpstaphunk, The Motet, JJ Grey. New Orleans and beyond.",
        "source": "archive",
        "query": {"collections": ["Lettuce", "GalacticFunk", "Dumpstaphunk", "TheMotet", "JJGreyandMOFRO", "Turkuaz"], "min_rating": 3.8},
    },
    {
        "slug": "newgrass",
        "name": "Newgrass",
        "description": "Yonder, Railroad Earth, Greensky, Stringdusters, Sam Bush, Del McCoury.",
        "source": "archive",
        "query": {"collections": ["YonderMountainStringBand", "RailroadEarth", "GreenskyBluegrass", "InfamousStringdusters", "SamBush", "DelMcCouryBand"], "min_rating": 4.0},
    },
    {
        "slug": "littlefeat",
        "name": "Little Feat",
        "description": "Waiting for Columbus and everything around it. '70s-'90s.",
        "source": "archive",
        "query": {"collections": ["LittleFeat"], "min_rating": 4.0},
    },
    {
        "slug": "ragtime",
        "name": "Ragtime",
        "description": "Ragtime and the ragtime era. Curated, Creative Commons and public domain.",
        "source": "cc",
        "query": {"items": ["kzz003", "C_1964_04_21", "AM_1973_01_04", "ragtime-cowboy-joe", "ragtimegoblinman00andr.omr", "danceofdaisies00unse_omr", "AM_1988_05_02"]},
    },
    {
        # ~13 hours of real rain and storms — field recordings, not synth loops. Every item
        # carries an explicit CC/PD licenseurl (the cc adapter refuses anything without one);
        # the aporee pair are short located field recordings that keep the texture honest.
        "slug": "rain",
        "name": "Rain & Thunder",
        "description": "Rain on roofs, night storms, distant thunder — the sleep channel. Curated field recordings, CC and public domain.",
        "source": "cc",
        "query": {"items": ["relaxingrainsounds", "naturesounds-soundtheraphy",
                            "rain-sounds-gentle-rain-thunderstorms", "GOLD_TAPE_46_Thunderstorm_Rain",
                            "thunderstorm_ms_relax_water", "Thunderstorm_1000",
                            "3-thunderstorm-at-sea-sounds-for-sleeping-relaxing-thunder-rain-ocean-sea",
                            "JacquesRicherCountryRain", "aporee_11681_13735", "aporee_4389_5761"]},
    },
    # ── the netlabel wing: golden-age CC netlabels, curated per channel and verified
    #    (mp3s + explicit licenseurl) against the live API before shipping. Mostly by-nc
    #    variants — fine for this personal tier; commercial_ok is recorded per track.
    {
        "slug": "ambient",
        "name": "Ambient",
        "description": "Drift music — Ambient Collective, laridae, Doc & Lena Selyanina. CC netlabels.",
        "source": "cc",
        "query": {"items": ["laridae031", "ambientcollective006", "SFIRE018", "laridae029",
                            "amb_col_light", "ambcol_dark", "mt008", "wh146"]},
    },
    {
        "slug": "dubtechno",
        "name": "Dub Techno",
        "description": "The Thinner/Autoplate catalog — deep, submerged, endless. CC netlabel canon.",
        "source": "cc",
        "query": {"items": ["thcomp001", "thn083", "apl020", "thn071", "thn057",
                            "thn067", "thn054", "thn084", "thn068", "apl037"]},
    },
    {
        "slug": "electronica",
        "name": "Electronica",
        "description": "Monotonik, Nullbomb, Vulpiano & friends — melodic IDM and braindance. CC netlabels.",
        "source": "cc",
        "query": {"items": ["mtcomp003", "nullbomb", "TAM033-Ronan_Dec", "MoxEarlyGanglions",
                            "ca015_va_cs", "Vkrsnl038MirandaShvangiradzeTalkToMeEp",
                            "Vkrsnl037CandlegravityAMomentForMyself"]},
    },
    {
        "slug": "jazzhop",
        "name": "Jazz-Hop",
        "description": "Dusted Wax Kingdom & co — dusty jazz samples over downtempo beats. CC netlabels.",
        "source": "cc",
        "query": {"items": ["DWK123", "DWK149", "DWK217", "DWK127", "DWK037",
                            "ca200_cjazz", "foot149", "foot090"]},
    },
    # ── the sleep wing, round two: more textures in the Rain & Thunder vein. All field
    #    recordings with explicit licenses; aporee items are short located recordings that
    #    rotate for variety.
    {
        "slug": "ocean",
        "name": "Ocean",
        "description": "Surf, swell, pebble beaches — the sea at night. Curated field recordings, CC and public domain.",
        "source": "cc",
        "query": {"items": ["ocean-sea-sounds", "aporee_37542_42986", "aporee_27992_32262",
                            "aporee_7678_9426", "aporee_9627_11535", "aporee_24168_28064",
                            "aporee_12490_14596", "aporee_65293_75412"]},
    },
    {
        "slug": "night",
        "name": "Summer Night",
        "description": "Crickets, tree frogs, high desert dark — the sound of a warm night. Curated field recordings.",
        "source": "cc",
        "query": {"items": ["aporee_22041_25600", "aporee_10410_12388", "aporee_10288_12240",
                            "aporee_2263_3221", "aporee_11613_13666", "aporee_4299_5666",
                            "aporee_30865_35494", "aporee_32354_37200",
                            "HowlerMonkeysAndTreeFrogsInCostaRica"]},
    },
    {
        "slug": "brook",
        "name": "Brook & Falls",
        "description": "Trickling streams, creeks, waterfalls — moving water, nothing else. Curated field recordings.",
        "source": "cc",
        "query": {"items": ["aporee_50949_58130", "aporee_34404_39551", "aporee_13900_16217",
                            "aporee_15642_18198", "aporee_11923_14000", "aporee_9685_11594",
                            "aporee_11090_13108", "aporee_16669_19368", "aporee_27311_31463",
                            "07BabblingBrook"]},
    },
    {
        "slug": "dub",
        "name": "Dub",
        "description": "Digital roots and dub — Disrupt, JAH Roots, Mastermind XS. CC netlabels.",
        "source": "cc",
        "query": {"items": ["jahroots_-_two_eyes", "JTREP01", "phoke24", "Brass_Islands_of_Dub",
                            "lcl22MastermindXs-OneDubManyRoots", "Starfrosch-DubLife",
                            "06-hardcore-dub-sessions"]},
    },
]

_topup_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(slug: str) -> threading.Lock:
    with _locks_guard:
        return _topup_locks.setdefault(slug, threading.Lock())


def ensure_seeded() -> None:
    for ch in SEED_CHANNELS:
        db.execute(
            "INSERT INTO channels(slug, name, description, source, query) "
            "VALUES(?,?,?,?,?) ON CONFLICT (slug) DO NOTHING",
            (ch["slug"], ch["name"], ch["description"], ch["source"],
             json.dumps(ch["query"])),
        )


# A section earns a broadcast channel once it holds this many records.
GENRE_CHANNEL_MIN = 3


def sync_genre_channels() -> None:
    """Sections become stations: 'From the Shelf — Jazz' etc, PRIVATE library
    channels derived from the crate itself. They appear when a section grows
    past GENRE_CHANNEL_MIN records and retire when it shrinks — the music
    volume is the source of truth, never a toggle. liquidsoap self-reloads on
    the channel-list change, so a new section simply comes on air."""
    import re as _re
    counts = {g["name"]: g["count"] for g in library.genre_counts()}
    want = {}
    for name, count in counts.items():
        if count >= GENRE_CHANNEL_MIN:
            slug = "shelf-" + _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            want[slug] = name
    for row in db.query("SELECT slug FROM channels WHERE slug LIKE ?", ("shelf-%",)):
        if row["slug"] not in want:
            db.execute("DELETE FROM channels WHERE slug=?", (row["slug"],))
    for slug, name in want.items():
        create_channel(slug, f"From the Shelf — {name}",
                       f"Your {name.lower()} records on shuffle, straight off the shelf.",
                       "library", {"genre": name})


# A vault category earns a mix channel once it holds this many tracks.
ATTIC_CHANNEL_MIN = 10


def sync_attic_channels() -> None:
    """The shelf server's declared categories become stations: 'The Vault — Jazz'
    etc, PRIVATE attic channels. Like sync_genre_channels, the source (the shelf
    server's catalog + its _genres.json) is the truth, never a toggle. These are
    MIX-ONLY (query.genre keeps them out of channels.liq), so 345 artists' worth
    of category churn never touches liquidsoap.

    NOTE the slug namespace: category channels are 'vault-<genre>' and are
    created AND retired here — never hand a non-category channel a 'vault-'
    slug (The Vault itself is 'vault', Artist Spotlight is 'spotlight')."""
    import re as _re
    want = {}
    for name, count in attic.genre_counts().items():
        if count >= ATTIC_CHANNEL_MIN:
            slug = "vault-" + _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            want[slug] = name
    for row in db.query("SELECT slug FROM channels WHERE slug LIKE ?", ("vault-%",)):
        if row["slug"] not in want:
            db.execute("DELETE FROM channels WHERE slug=?", (row["slug"],))
    for slug, name in want.items():
        create_channel(slug, f"The Vault — {name}",
                       f"{name} from the vault — the rescued collection on shuffle.",
                       "attic", {"genre": name})


def list_channels(streamable_only: bool = False) -> list[dict]:
    rows = db.query("SELECT * FROM channels WHERE enabled=1 ORDER BY created_at, slug")
    out = []
    for r in rows:
        r["query"] = json.loads(r.get("query") or "{}")
        # A library/attic channel is only real if the music is actually there —
        # otherwise it mounts and broadcasts silence. Surface that as `playable`
        # so the UI can say so, and keep it out of liquidsoap's mount list.
        # (attic probes its cached catalog — cheap after the first fetch, and an
        # unreachable shelf server honestly reads OFF AIR, not broken.)
        if r["source"] == "library":
            r["playable"] = bool(library.pick_tracks(r["query"], count=1))
        elif r["source"] == "attic":
            r["playable"] = bool(attic.pick_tracks(r["query"], count=1))
        else:
            r["playable"] = True
        # PRIVATE IS DERIVED, NOT DECLARED. Your own CDs (and the vault) are your own;
        # everything else is a public rebroadcast of something already public. Making it
        # a toggle would mean one wrong click puts a ripped album on the open internet —
        # so there is no toggle.
        r["private"] = (r["source"] in PRIVATE_SOURCES)
        if streamable_only and (r["source"] not in STREAMABLE_SOURCES or not r["playable"]):
            continue
        # genre stations are MIX-ONLY: clients play them as instant on-demand
        # shuffles — no icecast mount, no liquidsoap decode per section
        if streamable_only and r["query"].get("genre"):
            continue
        out.append(r)
    return out


def get_channel(slug: str) -> dict | None:
    rows = db.query("SELECT * FROM channels WHERE slug=?", (slug,))
    if not rows:
        return None
    ch = rows[0]
    ch["query"] = json.loads(ch.get("query") or "{}")
    return ch


def create_channel(slug: str, name: str, description: str, source: str, query: dict) -> dict:
    if source not in STREAMABLE_SOURCES:
        raise ValueError(f"source must be one of {', '.join(STREAMABLE_SOURCES)}")
    db.execute(
        "INSERT INTO channels(slug, name, description, source, query) VALUES(?,?,?,?,?) "
        "ON CONFLICT (slug) DO UPDATE SET name=excluded.name, "
        "description=excluded.description, source=excluded.source, query=excluded.query",
        (slug, name, description, source, json.dumps(query)),
    )
    return get_channel(slug)  # type: ignore[return-value]


def _recent_show_ids(slug: str) -> set[str]:
    rows = db.query(
        "SELECT show_id FROM history WHERE channel=? ORDER BY id DESC LIMIT 300", (slug,))
    rows += db.query("SELECT show_id FROM queue WHERE channel=?", (slug,))
    return {r["show_id"] for r in rows if r.get("show_id")}


def _enqueue_show_channel(ch: dict, adapter) -> int:
    show = adapter.pick_show(ch["query"], _recent_show_ids(ch["slug"]))
    if not show or not show["tracks"]:
        return 0
    album = f"{show['title']}"
    artist = str(show.get("creator") or "")
    lic = str(show.get("licenseurl") or "")
    comm = 1 if show.get("commercial_ok", True) else 0
    db.executemany(
        "INSERT INTO queue(channel, url, title, artist, album, show_id, licenseurl, "
        "commercial_ok) VALUES(?,?,?,?,?,?,?,?)",
        [(ch["slug"], t["url"], t["title"], artist, album, show["identifier"], lic, comm)
         for t in show["tracks"]],
    )
    return len(show["tracks"])


def _enqueue_library(ch: dict) -> int:
    tracks = library.pick_tracks(ch["query"])
    if not tracks:
        return 0
    # Each top-up is its own "show" so On Demand can reconstruct it. An empty
    # show_id is FALSY, and api_show treats falsy as "nothing loaded" — which
    # would leave every library channel permanently empty in On Demand, the
    # moment there are actually files to play.
    show_id = f"library-{ch['slug']}-{int(time.time())}"
    db.executemany(
        "INSERT INTO queue(channel, url, title, artist, album, show_id) VALUES(?,?,?,?,?,?)",
        [(ch["slug"], t["url"], t["title"], t["artist"], t["album"], show_id) for t in tracks],
    )
    log.info("enqueue_library: channel=%s queued=%d albums=%d show_id=%s",
             ch["slug"], len(tracks), len({t["album"] for t in tracks}), show_id)
    return len(tracks)


def _enqueue_attic(ch: dict) -> int:
    tracks = attic.pick_tracks(ch["query"])
    if not tracks:
        return 0
    # like library: each top-up is its own "show" so On Demand can reconstruct it
    show_id = f"attic-{ch['slug']}-{int(time.time())}"
    db.executemany(
        "INSERT INTO queue(channel, url, title, artist, album, show_id) VALUES(?,?,?,?,?,?)",
        [(ch["slug"], t["url"], t["title"], t["artist"], t["album"], show_id) for t in tracks],
    )
    log.info("enqueue_attic: channel=%s queued=%d artists=%d show_id=%s",
             ch["slug"], len(tracks), len({t["artist"] for t in tracks}), show_id)
    return len(tracks)


def ensure_queue(slug: str) -> int:
    """Top up a channel if it's running low. Returns number of tracks added."""
    ch = get_channel(slug)
    if not ch:
        return 0
    lock = _lock_for(slug)
    if not lock.acquire(blocking=False):
        return 0  # a top-up is already in flight
    try:
        unserved = db.query(
            "SELECT COUNT(*) AS n FROM queue WHERE channel=? AND served=0", (slug,))[0]["n"]
        if unserved >= config.MIN_QUEUE:
            return 0
        if ch["source"] in SHOW_ADAPTERS:
            return _enqueue_show_channel(ch, SHOW_ADAPTERS[ch["source"]])
        if ch["source"] == "library":
            return _enqueue_library(ch)
        if ch["source"] == "attic":
            return _enqueue_attic(ch)
        return 0
    finally:
        lock.release()


# ---------------------------------------------------------------- prefetch

def prefetch(slug: str, count: int = 3) -> None:
    """Download the next few remote tracks into the shared cache volume."""
    if not config.PREFETCH:
        return
    rows = db.query(
        "SELECT * FROM queue WHERE channel=? AND served=0 AND local_path IS NULL "
        "AND url LIKE 'http%' ORDER BY id LIMIT ?", (slug, count))
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    for row in rows:
        dest = os.path.join(config.CACHE_DIR, f"{slug}-{row['id']}.mp3")
        try:
            with httpx.stream("GET", row["url"], timeout=60, follow_redirects=True) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes(1 << 16):
                        f.write(chunk)
            db.execute("UPDATE queue SET local_path=? WHERE id=?", (dest, row["id"]))
        except Exception:
            try:
                os.unlink(dest)
            except OSError:
                pass


def _cleanup_cache(slug: str, keep_last: int = 2) -> None:
    rows = db.query(
        "SELECT id, local_path FROM queue WHERE channel=? AND served=1 "
        "AND local_path IS NOT NULL ORDER BY id DESC", (slug,))
    for row in rows[keep_last:]:
        try:
            if row["local_path"] and os.path.exists(row["local_path"]):
                os.unlink(row["local_path"])
        except OSError:
            pass
        db.execute("UPDATE queue SET local_path=NULL WHERE id=?", (row["id"],))


# ---------------------------------------------------------------- next track

def _annotate(row: dict) -> str:
    def esc(s: str) -> str:
        return str(s or "").replace("\\", "").replace('"', "'")
    src = _for_liquidsoap(row["url"])          # /music/... -> an absolute url it can fetch
    if row.get("local_path") and os.path.exists(row["local_path"]):
        src = row["local_path"]
    return (f'annotate:title="{esc(row["title"])}",artist="{esc(row["artist"])}",'
            f'album="{esc(row["album"])}":{src}')


def _for_liquidsoap(url: str) -> str:
    """The queue stores library/attic tracks as same-origin urls ("/music/x.mp3",
    "/attic/<root>/x.mp3") so the BROWSER can play them directly (on-demand + the Web
    Audio EQ). liquidsoap is a different container and needs an absolute one it can
    actually fetch."""
    return (f"{config.INTERNAL_URL}{url}?k={config.MUSIC_KEY}"
            if url.startswith(("/music/", "/attic/")) else url)


def next_track(slug: str) -> str:
    """Called by liquidsoap. Returns an annotate: URI, or '' if nothing queued."""
    rows = db.query(
        "SELECT * FROM queue WHERE channel=? AND served=0 ORDER BY id LIMIT 1", (slug,))
    if not rows:
        added = ensure_queue(slug)
        if added:
            prefetch(slug, count=1)  # grab at least the first one synchronously
        rows = db.query(
            "SELECT * FROM queue WHERE channel=? AND served=0 ORDER BY id LIMIT 1", (slug,))
        if not rows:
            return ""
    row = rows[0]
    db.execute("UPDATE queue SET served=1 WHERE id=?", (row["id"],))
    db.execute(
        "INSERT INTO history(channel, title, artist, album, show_id) VALUES(?,?,?,?,?)",
        (slug, row["title"], row["artist"], row["album"], row["show_id"]))
    set_nowplaying(slug, row["title"], row["artist"], row["album"], row["url"])

    def background() -> None:
        try:
            ensure_queue(slug)
            prefetch(slug)
            _cleanup_cache(slug)
        except Exception:
            pass

    threading.Thread(target=background, daemon=True).start()
    return _annotate(row)


# ---------------------------------------------------------------- now playing

def set_nowplaying(slug: str, title: str, artist: str, album: str, url: str = "") -> None:
    """Record what's on air. The url rides along so the UI can Like the current
    track — a favourite is worthless if it can't be played back.

    Two callers race here: next_track() knows the url, but liquidsoap then POSTs
    /api/nowplaying for the same track WITHOUT one when it actually starts
    playing. Last write wins, so the POST would silently blank the url and make
    the on-air track unlikeable. Rather than depend on ordering, resolve a
    missing url from the queue row that fed this track.
    """
    if not url:
        rows = db.query(
            "SELECT url FROM queue WHERE channel=? AND title=? AND served=1 "
            "ORDER BY id DESC LIMIT 1", (slug, title))
        if rows:
            url = rows[0]["url"] or ""
    db.execute(
        "INSERT INTO nowplaying(channel, title, artist, album, url, updated_at) "
        "VALUES(?,?,?,?,?,to_char(now() AT TIME ZONE 'utc','YYYY-MM-DD HH24:MI:SS')) "
        "ON CONFLICT(channel) DO UPDATE SET title=excluded.title, artist=excluded.artist, "
        "album=excluded.album, url=excluded.url, updated_at=excluded.updated_at",
        (slug, title, artist, album, url))


_ICE_TTL = 2.0
_ice_cache: dict = {"at": 0.0, "mounts": {}}
_ice_lock = threading.Lock()


def _icecast_on_air() -> dict[str, str]:
    """What icecast is ACTUALLY transmitting, per mount.

    This is the only honest answer to "what's playing". The queue is NOT:
    liquidsoap PREFETCHES the next request while the current track is still on
    air, so /api/next — and the nowplaying it writes — runs a whole track ahead
    of the broadcast. icecast sets a mount's metadata when the track reaches the
    encoder, which is precisely what listeners are hearing.

    Cached briefly; the UI polls this every few seconds and icecast shouldn't wear it.
    """
    with _ice_lock:
        if time.time() - _ice_cache["at"] < _ICE_TTL:
            return _ice_cache["mounts"]
    mounts: dict[str, str] = {}
    try:
        r = httpx.get(f"{config.ICECAST_ORIGIN}/status-json.xsl", timeout=3)
        src = r.json().get("icestats", {}).get("source", [])
        src = src if isinstance(src, list) else [src]
        for s in src:
            mount = str(s.get("listenurl", "")).rsplit("/", 1)[-1]
            if mount:
                mounts[mount] = str(s.get("title") or "")
    except Exception:
        pass                                    # icecast down: fall back to the table
    with _ice_lock:
        _ice_cache.update(at=time.time(), mounts=mounts)
    return mounts


def get_nowplaying(slug: str) -> dict:
    rows = db.query("SELECT * FROM nowplaying WHERE channel=?", (slug,))
    fallback = rows[0] if rows else {
        "channel": slug, "title": "", "artist": "", "album": "", "url": ""}

    on_air = _icecast_on_air().get(slug, "")
    if not on_air:
        return fallback

    # icecast gives one flat string ("Artist - Title"), and titles can contain
    # dashes — so don't split it. Match it against the tracks we recently served
    # on this channel and take the row whose title actually appears in it. That
    # gives back the structured record (artist, album, url) the UI needs, and the
    # url is what makes the on-air track Likeable.
    recent = db.query(
        "SELECT title, artist, album, url FROM queue WHERE channel=? AND served=1 "
        "ORDER BY id DESC LIMIT 12", (slug,))
    for row in recent:
        t = (row["title"] or "").strip()
        if t and t.lower() in on_air.lower():
            return {"channel": slug, "title": t, "artist": row["artist"],
                    "album": row["album"], "url": row["url"] or ""}
    return fallback


def queue_status(slug: str) -> dict:
    upcoming = db.query(
        "SELECT title, artist, album FROM queue WHERE channel=? AND served=0 "
        "ORDER BY id LIMIT 15", (slug,))
    n = db.query("SELECT COUNT(*) AS n FROM queue WHERE channel=? AND served=0", (slug,))[0]["n"]
    return {"channel": slug, "unserved": n, "upcoming": upcoming,
            "nowplaying": get_nowplaying(slug)}


def clear_queue(slug: str) -> int:
    rows = db.query(
        "SELECT local_path FROM queue WHERE channel=? AND served=0 "
        "AND local_path IS NOT NULL", (slug,))
    for row in rows:  # don't orphan prefetched files in the cache volume
        try:
            os.unlink(row["local_path"])
        except OSError:
            pass
    return db.execute("DELETE FROM queue WHERE channel=? AND served=0", (slug,))


def enqueue_show(slug: str, identifier: str, clear: bool = False) -> int:
    """Queue a specific show on a channel (DJ tool).

    The channel's source picks the adapter: archive identifiers for archive
    channels, YYYY-MM-DD dates for phishin channels.
    """
    ch = get_channel(slug)
    adapter = SHOW_ADAPTERS.get((ch or {}).get("source", ""), archive)
    if clear:
        clear_queue(slug)
    show = adapter.get_show(identifier)
    if not show["tracks"]:
        return 0
    db.executemany(
        "INSERT INTO queue(channel, url, title, artist, album, show_id) VALUES(?,?,?,?,?,?)",
        [(slug, t["url"], t["title"], str(show.get("creator") or ""), show["title"],
          show["identifier"]) for t in show["tracks"]],
    )
    return len(show["tracks"])


# ---------------------------------------------------------------- skip

def skip(slug: str) -> bool:
    """Skip the current track via liquidsoap's telnet server.

    Commands are named after the sources in radio.liq. The icecast *output*
    (`out_<slug>`) owns the playing track, so `out_<slug>.skip` is the one that
    actually drops it. There is no `<slug>.skip` — the request.dynamic queue only
    offers `<slug>.flush_and_skip`, which also throws away everything prefetched,
    so it's a last resort.

    Liquidsoap answers "Done!" or "ERROR ...". A connected socket is NOT proof of
    a skip: sending a command that doesn't exist still connects and still sends,
    which is how this used to report success while the track played on.
    """
    for cmd in (f"out_{slug}.skip", f"{slug}.flush_and_skip"):
        try:
            with socket.create_connection(
                    (config.LIQUIDSOAP_HOST, config.LIQUIDSOAP_TELNET_PORT), timeout=3) as s:
                s.sendall(f"{cmd}\nquit\n".encode())
                reply = s.recv(4096).decode(errors="replace")
        except OSError:
            continue
        if "ERROR" not in reply.upper():
            return True
    return False
