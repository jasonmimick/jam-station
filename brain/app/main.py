import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from . import channels, config, db, dj

STATIC = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    db.init()
    channels.ensure_seeded()
    yield


app = FastAPI(title="jam-station brain", lifespan=lifespan)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


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


# Same-origin proxy for the icecast mounts. icecast is a separate slab app on
# its own origin, so a browser served this page can't reach it directly (esp.
# through a tunnel). Streaming it through here means one hostname serves both
# the UI and the audio — the front-end just uses /stream/<slug>.
ICECAST_ORIGIN = os.environ.get("ICECAST_ORIGIN", "http://jam-icecast:8000")


@app.get("/stream/{slug}")
async def stream(slug: str):
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

    async def body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        body(), media_type=upstream.headers.get("content-type", "audio/mpeg"))


# ---------------------------------------------------------------- channels

@app.get("/api/channels")
def api_channels():
    return channels.list_channels()


@app.get("/api/channels.liq", response_class=PlainTextResponse)
def api_channels_liq():
    """Channel list for liquidsoap: one 'slug|Display Name' per line."""
    chans = channels.list_channels(streamable_only=True)
    return "\n".join(f"{c['slug']}|{c['name']}" for c in chans)


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


@app.get("/api/queue")
def api_queue(channel: str):
    return channels.queue_status(channel)


class ChannelRef(BaseModel):
    channel: str


@app.post("/api/skip")
def api_skip(ref: ChannelRef):
    return {"skipped": channels.skip(ref.channel)}


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
    return {"channel": channel, "show_id": show_id,
            "album": rows[0]["album"] if rows else "",
            "tracks": rows, "playing": playing}


# ---------------------------------------------------------------- AI DJ

class ChatBody(BaseModel):
    messages: list[dict]


@app.post("/api/chat")
def api_chat(body: ChatBody):
    reply = dj.chat(body.messages)
    return {"reply": reply}


# ---------------------------------------------------------------- debug

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
