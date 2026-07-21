import json
import os
import re
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, PlainTextResponse,
                               RedirectResponse, StreamingResponse)
from pydantic import BaseModel

from . import admin, auth, channels, config, covers, db, dj, engineer, presence, spot

STATIC = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    db.init()
    channels.ensure_seeded()
    channels.sync_genre_channels()
    try:
        channels.sync_attic_channels()   # vault categories -> stations; one HTTP call,
    except Exception:                    # and an absent shelf server must never block boot
        pass
    auth.ensure_owner()      # the owner is config, not a signup — he never approves himself
    covers.kick()            # backfill album art + year in the background
    yield


app = FastAPI(title="jam-station brain", lifespan=lifespan)


@app.get("/health")
def health():
    return {"ok": True}


# A phone and a desktop want genuinely different apps, not one page bent to fit both — the
# desktop is a 3-pane console, the phone is a gallery + a pinned player. So we serve two files
# and pick by user-agent. Overrides: ?m=1 forces mobile (to test from a laptop), ?desktop=1
# forces the console (the escape hatch if the sniff is ever wrong on a tablet).
_MOBILE_UA = re.compile(r"iPhone|Android.+Mobile|Windows Phone|iPod", re.I)


@app.get("/")
def index(request: Request, m: str = "", desktop: str = ""):
    ua = request.headers.get("user-agent", "")
    mobile = m == "1" or (desktop != "1" and bool(_MOBILE_UA.search(ua)))
    # no-cache = the browser MAY keep a copy but must revalidate before using it (cheap 304 if
    # unchanged). Without this the page ships only a Last-Modified, and mobile Safari happily
    # serves a stale index for hours — which is why a fresh deploy kept showing the old UI.
    return FileResponse(os.path.join(STATIC, "mobile.html" if mobile else "index.html"),
                        headers={"Cache-Control": "no-cache"})


@app.get("/dad")
def dad(request: Request):
    """Dad mode: a dead-simple full-screen radio — big station tiles, one play button,
    nothing to learn. Public like the radio itself. The affiliate/family front-end starts
    here (see DESIGN-family-radio)."""
    return FileResponse(os.path.join(STATIC, "dad.html"), headers={"Cache-Control": "no-cache"})


@app.get("/guide")
def guide(request: Request):
    """The contributor how-to (Tailscale → jam-inbox). Public — it's just instructions, and
    the whole point is a family member can open the link and follow it. Self-referential:
    lives on the station it teaches you to contribute to."""
    return FileResponse(os.path.join(STATIC, "guide.html"), headers={"Cache-Control": "no-cache"})


@app.get("/session")
def session_page(request: Request):
    """Download page for the Session Mac app — with the once-only Gatekeeper install steps."""
    return FileResponse(os.path.join(STATIC, "session.html"), headers={"Cache-Control": "no-cache"})


@app.get("/session/download")
def session_download():
    """The Session Mac app zip. Lives in the music VOLUME (survives redeploys, not in git —
    it's a build artifact); re-copy on a new build. Response, not upload, so no CF size cap."""
    p = os.path.join(config.MUSIC_DIR, "_downloads", "Session-mac.zip")
    if not os.path.exists(p):
        raise HTTPException(404, "no build hosted yet")
    return FileResponse(p, media_type="application/zip", filename="Session-mac.zip")


# Installable on a phone: a home-screen icon and a full-screen player instead of
# browser chrome. He listens walking around; this makes it feel like an app.
@app.get("/manifest.json")
def manifest():
    return FileResponse(os.path.join(STATIC, "manifest.json"), media_type="application/manifest+json")


@app.get("/icon-{size}.png")
def icon(size: str):
    if size not in ("192", "512"):
        raise HTTPException(404, "no such icon")
    return FileResponse(os.path.join(STATIC, f"icon-{size}.png"), media_type="image/png")


@app.get("/stations/{slug}.jpg")
def station_photo(slug: str):
    """Channel art: a curated photo per station (static/stations/<slug>.jpg). Public like
    the icons — a picture of a banjo gates nothing. Slugs come from our own db, but the
    path is caller-supplied, so refuse anything that isn't a plain slug."""
    if not re.fullmatch(r"[a-z0-9-]+", slug or ""):
        raise HTTPException(404, "no such station art")
    p = os.path.join(STATIC, "stations", f"{slug}.jpg")
    if not os.path.exists(p):
        raise HTTPException(404, "no such station art")
    return FileResponse(p, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})


# Same-origin proxy for the icecast mounts. icecast is a separate slab app on
# its own origin, so a browser served this page can't reach it directly (esp.
# through a tunnel). Streaming it through here means one hostname serves both
# the UI and the audio — the front-end just uses /stream/<slug>.
ICECAST_ORIGIN = os.environ.get("ICECAST_ORIGIN", "http://jam-icecast:8000")


def _is_member(request: Request) -> bool:
    # whoami() ALREADY refuses anyone not approved — pending, revoked, expired all come back
    # None. Re-checking a `status` field here looked careful and was the opposite: whoami
    # doesn't return one, so the check read undefined, compared false, and welded the door
    # shut for everybody. The gate looked locked and was actually broken. One owner of the
    # invariant; ask it, don't re-derive it.
    return auth.whoami(request.cookies.get(config.SESSION_COOKIE)) is not None


@app.get("/music/{path:path}")
def music(path: str, request: Request, k: str = ""):
    """Serve the record library over HTTP.

    This exists because slab volumes are PER-APP: liquidsoap can never see the brain's
    /music disk, no matter what we mount. It CAN fetch a url — which is already how every
    archive.org track reaches it. So the brain becomes the library's origin server, and
    the same url plays in the browser (same-origin, so the EQ and on-demand work on your
    own records too). One volume, one owner, no sharing.

    Members only — these are Jason's actual CDs, not a public rebroadcast.
    """
    if k != config.MUSIC_KEY and not _is_member(request):
        raise HTTPException(403, "members only")
    full = os.path.realpath(os.path.join(config.MUSIC_DIR, path))
    if not full.startswith(os.path.realpath(config.MUSIC_DIR) + os.sep):
        raise HTTPException(403, "no")          # ../../etc/passwd
    if not os.path.isfile(full):
        raise HTTPException(404, "no such track")
    # music AND cover art come through here — serve a .jpg as an image, mp3 as seekable audio.
    mt = "image/jpeg" if full.lower().endswith((".jpg", ".jpeg")) else \
         "image/png" if full.lower().endswith(".png") else "audio/mpeg"
    return FileResponse(full, media_type=mt)             # FileResponse honours Range


@app.get("/attic/{path:path}")
async def attic_file(path: str, request: Request, k: str = ""):
    """Proxy vault audio from the shelf server (attic-server.py on the mini HOST).

    Same story as /music, one hop longer: the browser can't reach
    host.docker.internal and must not reach the shelf server at all — it's the
    owner's private music, so the members gate lives HERE, on the brain. One
    same-origin url then works everywhere: browser (mixes, on-demand, EQ) and
    liquidsoap (via ?k=, see channels._for_liquidsoap). Range passes through so
    seeking works end to end.
    """
    if k != config.MUSIC_KEY and not _is_member(request):
        raise HTTPException(403, "members only")
    if not config.ATTIC_SERVER_URL:
        raise HTTPException(404, "no shelf server configured")
    from urllib.parse import quote
    upstream_url = f"{config.ATTIC_SERVER_URL}/file/{quote(path)}"
    headers = {}
    if request.headers.get("range"):
        headers["Range"] = request.headers["range"]
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None))
    try:
        upstream = await client.send(
            client.build_request("GET", upstream_url, headers=headers), stream=True)
    except httpx.HTTPError:
        await client.aclose()
        raise HTTPException(502, "shelf server unreachable")
    if upstream.status_code >= 400:
        code = upstream.status_code
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(code, "no such track")

    async def body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    passthrough = {h: upstream.headers[h] for h in
                   ("content-length", "content-range", "accept-ranges", "content-type")
                   if h in upstream.headers}
    return StreamingResponse(body(), status_code=upstream.status_code, headers=passthrough)


@app.get("/stream/{slug}")
async def stream(slug: str, request: Request):
    ch = channels.get_channel(slug)
    if ch and ch["source"] in channels.PRIVATE_SOURCES and not _is_member(request):
        raise HTTPException(403, "members only")
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None))
    try:
        upstream = await client.send(
            client.build_request("GET", f"{ICECAST_ORIGIN}/{slug}"), stream=True)
    except httpx.HTTPError:
        await client.aclose()
        raise HTTPException(502, "stream source unreachable")
    if upstream.status_code != 200:
        code = upstream.status_code
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(code, "no such stream")

    # the open connection is the listener's presence — cookie tells us who (see presence.py)
    me = _me(request)
    sid = presence.stream_connect(me["name"] if me else "", me["email"] if me else "", slug)

    async def body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            presence.stream_disconnect(sid)
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        body(), media_type=upstream.headers.get("content-type", "audio/mpeg"))


# ---------------------------------------------------------------- channels

@app.get("/api/channels")
def api_channels(request: Request):
    chans = channels.list_channels()
    for c in chans:   # curated photo, if one exists — the UI falls back to a placard
        if os.path.exists(os.path.join(STATIC, "stations", f"{c['slug']}.jpg")):
            c["art_url"] = f"/stations/{c['slug']}.jpg"
    if _is_member(request):
        return chans
    return [c for c in chans if not c["private"]]   # your CDs aren't on the public dial


@app.get("/api/channels.liq", response_class=PlainTextResponse)
def api_channels_liq():
    """Channel list for liquidsoap: one 'slug|Display Name' per line."""
    chans = channels.list_channels(streamable_only=True)
    # Canonical (sorted) order so a nondeterministic DB row order can never make
    # liquidsoap misread a stable channel set as "changed" and restart its mounts.
    lines = sorted(f"{c['slug']}|{c['name']}" for c in chans)
    return "\n".join(lines)


# ---------------------------------------------------------------- playback

@app.get("/api/next", response_class=PlainTextResponse)
def api_next(channel: str):
    """Liquidsoap polls this for the next track (annotate: URI or empty)."""
    return channels.next_track(channel)


class NowPlaying(BaseModel):
    channel: str
    title: str = ""
    artist: str = ""
    album: str = ""


@app.post("/api/nowplaying")
def api_nowplaying_set(np: NowPlaying):
    channels.set_nowplaying(np.channel, np.title, np.artist, np.album)
    return {"ok": True}


@app.get("/api/nowplaying")
def api_nowplaying(channel: str):
    return channels.get_nowplaying(channel)


@app.get("/api/dial")
def api_dial():
    """Now-playing across the whole dial in one call — so a client can show
    what every channel is on without a request per channel. Mix-only genre
    stations are skipped (each listener has their own 'now')."""
    out = {}
    for ch in channels.list_channels():
        if ch["query"].get("genre"):
            continue
        np = channels.get_nowplaying(ch["slug"])
        if np.get("title"):
            out[ch["slug"]] = {"title": np.get("title", ""),
                               "artist": np.get("artist", ""),
                               "album": np.get("album", "")}
    return out


@app.get("/api/queue")
def api_queue(channel: str):
    return channels.queue_status(channel)


class ChannelRef(BaseModel):
    channel: str


@app.post("/api/skip")
def api_skip(ref: ChannelRef):
    return {"skipped": channels.skip(ref.channel)}


# ---------------------------------------------------------------- rip status

@app.get("/api/rip")
def api_rip():
    """What the CD ripper is doing, for the UI. The ripper runs on the HOST and can't call in,
    but it CAN drop a status file into the music volume (which the brain owns) via docker — so
    it writes /music/.rip-status per track and we just read it. Stale (>90s untouched) = the
    ripper died or finished without a clean 'done', so report idle rather than a frozen bar."""
    p = os.path.join(config.MUSIC_DIR, ".rip-status")
    try:
        # per-track heartbeat; this slow drive can take >2min on one track, so don't call it
        # idle until well past that or the bar flickers to "not ripping" mid-rip.
        if time.time() - os.stat(p).st_mtime > 300:
            return {"state": "idle"}
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {"state": "idle"}


# ---------------------------------------------------------------- catalog (your records)

@app.get("/api/library/albums")
def api_library_albums(request: Request, response: Response):
    """Browse the record crate: one entry per ripped album. Members only — these are Jason's
    actual CDs. Returns [] (not 403) for anonymous, so the UI just shows no catalog rather
    than erroring; the audio itself is still gated at /music and /stream."""
    from .adapters import library
    response.headers["Cache-Control"] = "no-store"   # Safari was caching this and hiding new rips
    if not _is_member(request):
        return []
    covers.kick()            # a new album may have landed; enrich art/year in the background
    return library.list_albums()


@app.post("/api/library/cover")
def set_cover(request: Request, dir: str = Form(...), photo: UploadFile = File(...),
              type: str = Form("")):
    """Owner drops a photo on an album. Default (type front/cover/empty) is the front cover —
    saved as _cover.jpg, which the enricher then leaves alone. Any other type (tracklist, back,
    disc, …) is a companion image saved as _art-<slug>.jpg in the same folder; there can be many."""
    from .adapters import library
    if not _is_member(request):
        raise HTTPException(403, "members only")
    base = os.path.realpath(config.MUSIC_DIR)
    full = os.path.realpath(os.path.join(config.MUSIC_DIR, dir))
    if full != base and not full.startswith(base + os.sep):
        raise HTTPException(403, "no")                    # ../../ escape
    if not os.path.isdir(full):
        raise HTTPException(404, "no such album")
    t = (type or "").strip().lower()
    if t in ("", "front", "cover"):
        slug, fname = "front", "_cover.jpg"
    else:
        slug = library.art_slug(t)
        if not slug:
            raise HTTPException(400, "bad type")
        fname = f"_art-{slug}.jpg"
    data = photo.file.read()
    if not data:
        raise HTTPException(400, "empty image")
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, "image too large")
    with open(os.path.join(full, fname), "wb") as f:
        f.write(data)
    return {"ok": True, "type": slug}


@app.get("/api/library/album")
def api_library_album(request: Request, dir: str):
    """One album as a playable, ordered tracklist — the on-demand counterpart to a station."""
    from .adapters import library
    if not _is_member(request):
        raise HTTPException(403, "members only")
    tracks = library.album_tracks(dir)
    if not tracks:
        raise HTTPException(404, "no such album")
    return {"dir": dir, "album": tracks[0]["album"], "artist": tracks[0]["artist"],
            "tracks": tracks, "images": library.album_images(dir), "playing": -1}


# ---------------------------------------------------------------- vinyl (the record wall)

@app.get("/api/vinyl")
def api_vinyl(request: Request):
    """The LP wall — catalog only, no audio (DESIGN-vinyl.md). [] for anonymous,
    same spirit as the shelf. Fetching it keeps the nightly sync honest."""
    from . import discogs
    if not _is_member(request):
        return []
    discogs.kick()
    return discogs.records()


@app.get("/api/vinyl/sections")
def api_vinyl_sections(request: Request):
    from . import discogs
    if not _is_member(request):
        return []
    return discogs.sections()


@app.post("/api/vinyl/sync")
def api_vinyl_sync(request: Request):
    """Owner kick — a background sync starts if one isn't already running."""
    from . import discogs
    if not _is_member(request):
        raise HTTPException(403, "members only")
    discogs.kick(max_age_hours=0)
    return {"started": True}


@app.get("/api/library/genres")
def api_library_genres(request: Request):
    """The shelf's sections, biggest first. [] for anonymous, same spirit as the catalog."""
    from .adapters import library
    if not _is_member(request):
        return []
    return library.genre_counts()


@app.get("/api/library/mix")
def api_library_mix(request: Request, genre: str, count: int = 30):
    """A shuffled tracklist across every album in a section — 'a jazz mix from the shelf'.
    Show-shaped, so every client plays it through the on-demand machinery it already has."""
    from .adapters import library
    if not _is_member(request):
        raise HTTPException(403, "members only")
    tracks = library.build_mix(genre, count)
    if not tracks:
        raise HTTPException(404, f"nothing on the shelf under {genre!r}")
    return {"channel": "mix", "album": f"{genre} Mix", "artist": "the shelf",
            "tracks": tracks, "playing": -1}


@app.get("/api/attic/cover")
def api_attic_cover(request: Request, artist: str, album: str, k: str = ""):
    """Album art for vault tracks, fetched LAZILY: the vault has no curated covers and
    nobody is going to hand-curate 16,000 tracks — so the first time a client looks at
    an album, we ask iTunes (covers._itunes_cover, same fallback the shelf uses), cache
    the sleeve on the cache volume, and every later look is instant. A miss is cached
    too (.none marker) so an obscure album can't make every render re-hit iTunes."""
    if k != config.MUSIC_KEY and not _is_member(request):
        raise HTTPException(403, "members only")
    slug = re.sub(r"[^a-z0-9]+", "-", f"{artist} {album}".lower()).strip("-")[:80]
    if not slug:
        raise HTTPException(404, "no art")
    art_dir = os.path.join(config.CACHE_DIR, "attic-art")
    os.makedirs(art_dir, exist_ok=True)
    dest = os.path.join(art_dir, slug + ".jpg")
    if os.path.exists(dest):
        return FileResponse(dest, media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=86400"})
    if os.path.exists(dest + ".none"):
        raise HTTPException(404, "no art found")
    if covers._itunes_cover(artist, album, dest):
        return FileResponse(dest, media_type="image/jpeg",
                            headers={"Cache-Control": "public, max-age=86400"})
    open(dest + ".none", "w").close()
    raise HTTPException(404, "no art found")


@app.get("/api/mix")
def api_mix(request: Request, slug: str, count: int = 30):
    """A mix for any MIX-ONLY channel (query.genre), dispatched by its source —
    the shelf's sections AND the vault's categories through one door. The older
    /api/library/mix stays for back-compat (Session still calls it)."""
    if not _is_member(request):
        raise HTTPException(403, "members only")
    ch = channels.get_channel(slug)
    genre = (ch or {}).get("query", {}).get("genre")
    if not ch or not genre:
        raise HTTPException(404, "not a mix channel")
    if ch["source"] == "attic":
        from .adapters import attic
        tracks, shelf = attic.build_mix(genre, count), "the vault"
    else:
        from .adapters import library
        tracks, shelf = library.build_mix(genre, count), "the shelf"
    if not tracks:
        raise HTTPException(404, f"nothing filed under {genre!r}")
    return {"channel": "mix", "album": f"{genre} Mix", "artist": shelf,
            "tracks": tracks, "playing": -1}


class GenreSet(BaseModel):
    dir: str
    genres: list[str] = []


@app.post("/api/library/genre")
def api_library_set_genre(body: GenreSet, request: Request):
    """Owner curation: pin an album's sections (any labels — the buckets are yours)."""
    from .adapters import library
    if not _is_member(request):
        raise HTTPException(403, "members only")
    if not library.set_genres(body.dir, body.genres):
        raise HTTPException(404, "no such album")
    channels.sync_genre_channels()      # curation can birth or retire a station
    return {"ok": True}


# ---------------------------------------------------------------- spot (photo -> music)

@app.post("/api/spot")
def api_spot(request: Request, photo: UploadFile = File(...)):
    """Snap a photo of music in the wild; Claude reads it and we match it to your crate or save
    it to the Spotted shelf. Sync def on purpose — the vision call blocks, so FastAPI runs it in
    a threadpool instead of stalling the event loop. Members only (it writes to your library)."""
    me = _me(request)
    if not me:
        raise HTTPException(403, "members only")
    data = photo.file.read()
    if not data:
        raise HTTPException(400, "empty photo")
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, "photo too large")
    media_type = photo.content_type if (photo.content_type or "").startswith("image/") else "image/jpeg"
    try:
        return spot.create_spot(data, media_type, me["email"])
    except Exception as e:
        raise HTTPException(502, f"couldn't identify: {e}")


@app.get("/api/spots")
def api_spots(request: Request):
    if not _is_member(request):
        return []
    return spot.list_spots()


class SpotRef(BaseModel):
    id: int


@app.post("/api/spot/delete")
def api_spot_delete(body: SpotRef, request: Request):
    if not _is_member(request):
        raise HTTPException(403, "members only")
    spot.delete_spot(body.id)
    return {"ok": True}


# ---------------------------------------------------------------- on demand

@app.get("/api/show")
def api_show(channel: str):
    """The tape currently on a channel, as a *playable* tracklist.

    The queue keeps served rows (and their direct MP3 url), so one show_id gives
    the whole show — what's played, what's on, what's left — with URLs. That's
    what lets the browser play a tape on demand (seek, scrub, jump, rewind)
    instead of riding the live broadcast, which has no buffer to seek in.
    """
    cur = db.query("SELECT show_id FROM queue WHERE channel=? AND served=1 "
                   "ORDER BY id DESC LIMIT 1", (channel,))
    if not cur or not cur[0]["show_id"]:
        return {"channel": channel, "album": "", "tracks": [], "playing": -1}
    show_id = cur[0]["show_id"]
    rows = db.query("SELECT title, artist, album, url, served FROM queue "
                    "WHERE channel=? AND show_id=? ORDER BY id", (channel, show_id))
    playing = max((i for i, r in enumerate(rows) if r["served"]), default=-1)
    # a library batch is a MIX across albums — labelling it with the first
    # track's album made a whole shelf station read as one record
    ch = channels.get_channel(channel)
    if ch and ch["source"] == "library":
        album = ch["name"]
    else:
        album = rows[0]["album"] if rows else ""
    return {"channel": channel, "show_id": show_id, "album": album,
            "tracks": rows, "playing": playing}


# ---------------------------------------------------------------- AI DJ

class ChatBody(BaseModel):
    messages: list[dict]


@app.post("/api/chat")
def api_chat(body: ChatBody):
    reply = dj.chat(body.messages)
    return {"reply": reply}


# ---------------------------------------------------------------- debug

class PresenceBeat(BaseModel):
    channel: str
    aid: str = ""      # anonymous device id from the UI, so signed-out listeners still count


@app.post("/api/presence")
def api_presence(body: PresenceBeat, request: Request):
    """On-demand heartbeat. Radio needs none — the open /stream connection is the presence."""
    me = _me(request)
    key = me["email"] if me else "anon:" + (body.aid or request.client.host or "?")[:24]
    presence.heartbeat(me["name"] if me else "", me["email"] if me else "",
                       key, body.channel[:80])
    return {"ok": True}


def _client_of(ua: str) -> str:
    """What kind of thing is speaking. URLSession's default UA leads with the bundle
    executable ('Session/1 CFNetwork/…', 'SessioniOS/1 …'); browsers say Mozilla."""
    u = (ua or "").lower()
    if "sessionios" in u:
        return "Session (iOS)"
    if u.startswith("session"):
        return "Session (Mac)"
    if "cfnetwork" in u or ("darwin" in u and "mozilla" not in u):
        return "Session app"
    if "mobile" in u and "mozilla" in u:
        return "phone web"
    return "web"


@app.middleware("http")
async def presence_touch(request: Request, call_next):
    # Any signed-in /api chatter means that client is IN THE ROOM — this is how the native
    # apps show up without heartbeat code of their own (they poll the dial anyway).
    if request.url.path.startswith("/api/"):
        me = _me(request)
        if me:
            presence.seen(me["email"], me["name"],
                          _client_of(request.headers.get("user-agent", "")))
    return await call_next(request)


# ---------------------------------------------------------------- the engineer's booth

def _is_owner(request: Request) -> bool:
    me = _me(request)
    return bool(me and me.get("role") == "owner")


@app.get("/admin")
def admin_page(request: Request):
    """Owner-only. 404 for everyone else — the booth's existence is nobody's business."""
    if not _is_owner(request):
        raise HTTPException(404, "not found")
    return FileResponse(os.path.join(STATIC, "admin.html"), headers={"Cache-Control": "no-cache"})


@app.get("/api/admin/status")
def api_admin_status(request: Request):
    if not _is_owner(request):
        raise HTTPException(404, "not found")
    return admin.status()


@app.post("/api/admin/chat")
def api_admin_chat(body: ChatBody, request: Request):
    if not _is_owner(request):
        raise HTTPException(404, "not found")
    return {"reply": engineer.chat(body.messages)}


@app.get("/api/listeners")
def api_listeners(request: Request):
    """Who's here. Members only — anonymous gets an empty room, not an error, in the same
    spirit as the catalog: the UI simply shows nothing rather than breaking."""
    if not _is_member(request):
        return {"count": 0, "listeners": [], "online": []}
    ls = presence.listeners()
    return {"count": len(ls), "listeners": ls, "online": presence.online()}


@app.get("/api/history")
def api_history(channel: str | None = None, limit: int = 30):
    """Play log. Omit `channel` for the whole station network (rows carry the
    channel so the UI can label them); pass one to scope it."""
    if channel:
        return db.query(
            "SELECT channel, title, artist, album, played_at FROM history WHERE channel=? "
            "ORDER BY id DESC LIMIT ?", (channel, limit))
    return db.query(
        "SELECT channel, title, artist, album, played_at FROM history "
        "ORDER BY id DESC LIMIT ?", (limit,))


# ---------------------------------------------------------------- auth
#
# IDENTITY ENHANCES, IT NEVER GATES. Nobody signs in to listen to the radio — every
# endpoint above works anonymously, exactly as before. Signing in ADDS: favourites that
# follow you across devices, your own listen history, and (later) a NAME your dad can see.
#
# ⚠️  NOTHING HERE ACTS ON A GET. Email clients (Outlook Safe Links, Gmail's proxy, corporate
#     scanners) prefetch every url in a message before a human sees it. A GET that approves,
#     approves for a scanner. A GET that burns a magic link burns it before it's clicked.
#     So: GET shows a confirm PAGE, and the action is a POST. Prefetchers don't POST.

def _me(request: Request) -> dict | None:
    return auth.whoami(request.cookies.get(config.SESSION_COOKIE))


def _https(request: Request) -> bool:
    """Behind the Cloudflare tunnel the app itself is spoken to over HTTP, so we cannot ask
    the request's own scheme — we have to trust the proxy's X-Forwarded-Proto. Getting this
    wrong either drops the cookie in production (Secure over a scheme it thinks is http) or
    marks it Secure on plain http, where the browser silently refuses to store it."""
    return (request.headers.get("x-forwarded-proto") or request.url.scheme) == "https"


def _set_session(resp: Response, email: str, ua: str, request: Request) -> None:
    resp.set_cookie(
        config.SESSION_COOKIE, auth.new_session(email, ua),
        max_age=config.SESSION_DAYS * 86400, httponly=True, samesite="lax",
        secure=_https(request), path="/",
    )


def _page(title: str, body: str) -> HTMLResponse:
    """Minimal, self-contained confirm page. Same signage palette as the app."""
    return HTMLResponse(f"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{background:#0F0F11;color:#fff;font:16px/1.6 "Helvetica Neue",Arial,sans-serif;
display:flex;align-items:center;justify-content:center;min-height:100dvh;margin:0;padding:24px}}
.c{{max-width:420px;width:100%}}h1{{font-size:20px;margin:0 0 14px}}
p{{color:#8C8C94;margin:0 0 18px}}button{{background:#FFD200;color:#12120C;border:0;
border-radius:2px;padding:14px 22px;font:inherit;font-weight:800;letter-spacing:.08em;
text-transform:uppercase;cursor:pointer;width:100%}}
a{{color:#FFD200}}.ok{{color:#2FD16A}}.err{{color:#F0402F}}</style>
<div class=c>{body}</div>""")


class AccessReq(BaseModel):
    invite: str = ""
    email: str
    name: str = ""
    note: str = ""


@app.get("/join", response_class=HTMLResponse)
def join_page(i: str = ""):
    """Requires a valid invite. Without this, /join is a public form that lets the entire
    internet flood the owner's inbox with approval requests."""
    if not auth.invite_ok(i):
        return _page("jam-station", "<h1 class=err>This invite isn't valid</h1>"
                                    "<p>Ask whoever sent it for a fresh link.</p>")
    return _page("Join jam-station", f"""
      <h1>⚡ jam-station</h1>
      <p>Ask for access. The station owner will get an email and approve you.</p>
      <form id=f>
        <input id=n placeholder="Your name" style="width:100%;padding:12px;margin-bottom:8px;
          background:#17171A;border:1px solid #2B2B31;color:#fff;border-radius:2px;font:inherit">
        <input id=e type=email required placeholder="you@example.com" style="width:100%;padding:12px;
          margin-bottom:8px;background:#17171A;border:1px solid #2B2B31;color:#fff;border-radius:2px;font:inherit">
        <input id=w placeholder="Who are you? (optional)" style="width:100%;padding:12px;
          margin-bottom:14px;background:#17171A;border:1px solid #2B2B31;color:#fff;border-radius:2px;font:inherit">
        <button type=submit>Ask for access</button>
      </form>
      <p id=m style="margin-top:16px"></p>
      <script>
      document.getElementById('f').onsubmit = async (ev) => {{
        ev.preventDefault();
        const r = await fetch('/api/auth/request-access', {{method:'POST',
          headers:{{'Content-Type':'application/json'}},
          body: JSON.stringify({{invite:{i!r}, email:document.getElementById('e').value,
                                name:document.getElementById('n').value,
                                note:document.getElementById('w').value}})}});
        const d = await r.json();
        const m = document.getElementById('m');
        if (d.error) {{ m.className='err'; m.textContent = d.error; return; }}
        document.getElementById('f').style.display='none';
        m.className='ok';
        m.textContent = d.already ? "You already have access — go sign in."
                                  : "Asked. You'll get an email once you're approved.";
      }};
      </script>""")


@app.post("/api/auth/request-access")
def api_request_access(body: AccessReq):
    return auth.request_access(body.invite, body.email, body.name, body.note)


@app.get("/auth/approve", response_class=HTMLResponse)
def approve_page(t: str = ""):
    """GET: shows who is asking. Approves NOTHING. (Scanners prefetch this.)"""
    rec = auth.approval_for(t)
    if not rec:
        return _page("Expired", "<h1 class=err>That link has expired</h1>"
                                "<p>Or it was already used.</p>")
    m = auth.member(rec["email"]) or {}
    note = f"<p>They said: “{m.get('note','')}”</p>" if m.get("note") else ""
    return _page("Approve", f"""
      <h1>Approve access?</h1>
      <p><b>{m.get('name') or rec['email']}</b><br>{rec['email']}</p>{note}
      <form method=post action=/auth/approve>
        <input type=hidden name=t value="{t}">
        <button type=submit>Approve</button>
      </form>""")


@app.post("/auth/approve", response_class=HTMLResponse)
async def approve_do(request: Request):
    form = await request.form()
    r = auth.approve(str(form.get("t", "")))
    if r.get("error"):
        return _page("Error", f"<h1 class=err>{r['error']}</h1>")
    return _page("Approved", f"<h1 class=ok>Approved</h1>"
                             f"<p>{r['email']} has been sent a way in.</p>")


class EmailReq(BaseModel):
    email: str


@app.post("/api/auth/login")
def api_login(body: EmailReq):
    """Send the magic link AND the code. Always answers the same, so this can't be used to
    discover who is a member."""
    auth.start_login(body.email)
    return {"ok": True}


@app.get("/auth/signin", response_class=HTMLResponse)
def signin_page(t: str = ""):
    """GET: shows a button. Signs in NOTHING. (A scanner prefetching this must not burn the
    token — that's the bug that makes magic links say 'already used'.)"""
    email = auth.peek_token(t)
    if not email:
        return _page("Expired", "<h1 class=err>That sign-in link has expired</h1>"
                                "<p>Ask for a new one — or use the code instead.</p>")
    return _page("Sign in", f"""
      <h1>Sign in to jam-station</h1><p>{email}</p>
      <form method=post action=/auth/signin>
        <input type=hidden name=t value="{t}">
        <button type=submit>Sign in</button>
      </form>""")


@app.post("/auth/signin")
async def signin_do(request: Request):
    form = await request.form()
    r = auth.redeem_token(str(form.get("t", "")))
    if r.get("error"):
        return _page("Error", f"<h1 class=err>{r['error']}</h1>")
    resp = _page("Signed in", '<h1 class=ok>You\'re in</h1>'
                              '<p><a href="/">Back to the radio →</a></p>')
    _set_session(resp, r["email"], request.headers.get("user-agent", ""), request)
    return resp


class CodeReq(BaseModel):
    email: str
    code: str


@app.post("/api/auth/code")
def api_code(body: CodeReq, request: Request, response: Response):
    """The code path — the whole reason a magic link isn't enough. It redeems the SAME login
    attempt on ANY device, so you can open the email on your phone and sign in on the laptop."""
    r = auth.redeem_code(body.email, body.code)
    if r.get("error"):
        raise HTTPException(400, r["error"])
    _set_session(response, r["email"], request.headers.get("user-agent", ""), request)
    return {"ok": True, "email": r["email"]}


# ---------------------------------------------------------------- access keys (the simple path)

@app.get("/k/{token}")
def key_link(token: str, request: Request):
    """Tap a personal link -> you're in. A GET that DOES act — deliberately, and safely: unlike
    an emailed magic link these are texted, and they're REUSABLE, so a link-preview bot that
    prefetches the URL just gets a throwaway cookie it discards; the real person taps and gets
    their own session, and the key still works. That reusability is exactly what makes 'tap
    once, listen forever' safe without a confirm page."""
    who = auth.key_login(token)
    if not who:
        return _page("Link not valid",
                     "<h1 class=err>That link isn't valid anymore</h1>"
                     "<p>Ask whoever invited you for a fresh one.</p>")
    resp = RedirectResponse("/", status_code=303)
    _set_session(resp, who["email"], request.headers.get("user-agent", ""), request)
    return resp


class KeyCodeReq(BaseModel):
    code: str


@app.post("/api/auth/key")
def api_key_code(body: KeyCodeReq, request: Request, response: Response):
    """One box, no email: whatever you type is tried as an access CODE first, then as a
    PASSPHRASE. So "jimmypage" (a passphrase) and "AD5PRVDE" (a code) both just sign you in."""
    who = auth.code_login(body.code) or auth.passphrase_login_any(body.code)
    if not who:
        raise HTTPException(400, "That code or passphrase isn't valid.")
    _set_session(response, who["email"], request.headers.get("user-agent", ""), request)
    return {"ok": True, "name": who["name"]}


class PassLoginReq(BaseModel):
    email: str
    passphrase: str


@app.post("/api/auth/passphrase")
def api_passphrase(body: PassLoginReq, request: Request, response: Response):
    """Sign in with email + passphrase — the durable path you set yourself and never lose."""
    who = auth.passphrase_login(body.email, body.passphrase)
    if not who:
        raise HTTPException(400, "Wrong email or passphrase.")
    _set_session(response, who["email"], request.headers.get("user-agent", ""), request)
    return {"ok": True, "name": who["name"]}


class SetPassReq(BaseModel):
    passphrase: str


@app.post("/api/auth/set-passphrase")
def api_set_passphrase(body: SetPassReq, request: Request):
    """Set (or change) your own passphrase. Must already be signed in — via link, code, or an
    existing passphrase. That's the bootstrap: tap your link once, then set this and you're
    never dependent on the link again."""
    me = _me(request)
    if not me:
        raise HTTPException(401, "not signed in")
    r = auth.set_passphrase(me["email"], body.passphrase)
    if r.get("error"):
        raise HTTPException(400, r["error"])
    return {"ok": True}


@app.post("/api/auth/signout")
def api_signout(request: Request, response: Response):
    auth.end_session(request.cookies.get(config.SESSION_COOKIE))
    response.delete_cookie(config.SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def api_me(request: Request):
    """Anonymous is a normal answer, not an error."""
    return {"user": _me(request)}


# ---------------------------------------------------------------- favourites

class FavSync(BaseModel):
    local: list[dict] = []


@app.post("/api/favourites/sync")
def api_fav_sync(body: FavSync, request: Request):
    """First sign-in MERGES the browser's likes into the account — never overwrites.

    You have likes in localStorage on your phone AND your laptop and the lists differ. If we
    overwrote, the very first thing this auth system would do is DELETE YOUR MUSIC.
    """
    me = _me(request)
    if not me:
        raise HTTPException(401, "not signed in")
    return {"favourites": auth.merge_favourites(me["email"], body.local)}


@app.get("/api/favourites")
def api_favs(request: Request):
    me = _me(request)
    if not me:
        raise HTTPException(401, "not signed in")
    return {"favourites": auth.favourites(me["email"])}


class FavOne(BaseModel):
    url: str
    title: str = ""
    artist: str = ""
    album: str = ""
    channel: str = ""


@app.post("/api/favourites/add")
def api_fav_add(body: FavOne, request: Request):
    me = _me(request)
    if not me:
        raise HTTPException(401, "not signed in")
    auth.add_favourite(me["email"], body.model_dump())
    return {"ok": True}


@app.post("/api/favourites/remove")
def api_fav_remove(body: FavOne, request: Request):
    me = _me(request)
    if not me:
        raise HTTPException(401, "not signed in")
    auth.remove_favourite(me["email"], body.url)
    return {"ok": True}


# ---------------------------------------------------------------- owner

class InviteReq(BaseModel):
    label: str = ""


@app.post("/api/owner/invite")
def api_invite(body: InviteReq, request: Request):
    me = _me(request)
    if not me or me["role"] != "owner":
        raise HTTPException(403, "owner only")
    raw = auth.create_invite(body.label)
    return {"invite": raw, "url": f"{config.PUBLIC_URL}/join?i={raw}"}


class AddPersonReq(BaseModel):
    name: str
    email: str = ""
    code: str = ""     # optional owner-chosen passcode; blank = we invent one


@app.post("/api/owner/add")
def api_owner_add(body: AddPersonReq, request: Request):
    """The dead-simple invite: owner adds a person (name + email, passcode optional) — the
    station EMAILS them their link + passcode, and the same card comes back to the owner as
    a fallback to text. The email is their identity — it's what they'll use if they set a
    passphrase. No approval step — the owner adding you IS the approval."""
    me = _me(request)
    if not me or me["role"] != "owner":
        raise HTTPException(403, "owner only")
    if not body.name.strip():
        raise HTTPException(400, "give them a name")
    code = ""
    if body.code.strip():
        code = auth.normalize_code(body.code)
        if not code:
            raise HTTPException(400, "passcode needs 6–24 letters/numbers")
    r = auth.create_key_member(body.name, contact=body.email, email=body.email, code=code)
    r["sent"] = bool("@" in r["email"]
                     and auth.send_key_email(r["name"], r["email"], r["link"], r["code"]))
    return r


@app.post("/api/owner/rotate")
def api_owner_rotate(body: EmailReq, request: Request):
    """Recovery: someone lost their link AND code. Issue a fresh pair; the old ones die."""
    me = _me(request)
    if not me or me["role"] != "owner":
        raise HTTPException(403, "owner only")
    r = auth.rotate_key(body.email)
    if not r:
        raise HTTPException(404, "no such person")
    r["sent"] = bool("@" in r["email"]
                     and auth.send_key_email(r["name"], r["email"], r["link"], r["code"]))
    return r


@app.get("/api/owner/members")
def api_members(request: Request):
    me = _me(request)
    if not me or me["role"] != "owner":
        raise HTTPException(403, "owner only")
    rows = db.query(
        "SELECT m.email, m.name, m.role, m.status, m.contact, m.created_at, "
        "  (SELECT COUNT(*) FROM access_keys k WHERE k.email=m.email AND k.revoked_at='') AS keys "
        "FROM members m ORDER BY m.created_at DESC")
    return {"members": rows}


@app.post("/api/owner/revoke")
def api_revoke(body: EmailReq, request: Request):
    """Slam the door: status AND every live session, immediately. This is why sessions are
    server-side rather than JWTs."""
    me = _me(request)
    if not me or me["role"] != "owner":
        raise HTTPException(403, "owner only")
    if auth.is_owner(body.email):
        raise HTTPException(400, "can't revoke the owner")
    auth.revoke(body.email)
    return {"ok": True}


# ---------------------------------------------------------------- personal radio (per-member handle)

@app.get("/api/u/{handle}")
def api_user(handle: str):
    """Whose radio is this — just the display name for a member's personal page. Minimal on
    purpose (no email, no status): it feeds a greeting, nothing more."""
    m = auth.member_by_handle(handle)
    if not m:
        raise HTTPException(404, "no such person")
    return {"name": m["name"] or "Radio", "handle": auth.handle_for(m["email"])}


@app.get("/{handle}")
def personal_radio(handle: str):
    """A member's own radio at their handle: jam-station.runslab.run/<handle>. The simple
    dial (idea #1), personalized with their name. Registered LAST so every real route wins
    first; an unknown handle 404s rather than shadowing anything. (Next: their contributed
    stations up top — needs upload attribution.)"""
    if not auth.member_by_handle(handle):
        raise HTTPException(404, "not found")
    return FileResponse(os.path.join(STATIC, "radio.html"), headers={"Cache-Control": "no-cache"})
