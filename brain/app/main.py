import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
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


# ---------------------------------------------------------------- AI DJ

class ChatBody(BaseModel):
    messages: list[dict]


@app.post("/api/chat")
def api_chat(body: ChatBody):
    reply = dj.chat(body.messages)
    return {"reply": reply}


# ---------------------------------------------------------------- debug

@app.get("/api/history")
def api_history(channel: str, limit: int = 30):
    return db.query(
        "SELECT title, artist, album, played_at FROM history WHERE channel=? "
        "ORDER BY id DESC LIMIT ?", (channel, limit))
