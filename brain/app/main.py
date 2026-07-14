import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import (FileResponse, HTMLResponse, PlainTextResponse,
                               StreamingResponse)
from pydantic import BaseModel

from . import auth, channels, config, db, dj

STATIC = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    db.init()
    channels.ensure_seeded()
    auth.ensure_owner()      # the owner is config, not a signup — he never approves himself
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


def _is_member(request: Request) -> bool:
    m = auth.whoami(request.cookies.get(config.SESSION_COOKIE))
    return bool(m and m.get("status") == "approved")


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
    return FileResponse(full, media_type="audio/mpeg")   # FileResponse honours Range


@app.get("/stream/{slug}")
async def stream(slug: str, request: Request):
    ch = channels.get_channel(slug)
    if ch and ch["source"] == "library" and not _is_member(request):
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
def api_channels(request: Request):
    chans = channels.list_channels()
    if _is_member(request):
        return chans
    return [c for c in chans if not c["private"]]   # your CDs aren't on the public dial


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


@app.get("/api/owner/members")
def api_members(request: Request):
    me = _me(request)
    if not me or me["role"] != "owner":
        raise HTTPException(403, "owner only")
    return {"members": db.query(
        "SELECT email, name, role, status, note, created_at, approved_at FROM members "
        "ORDER BY created_at DESC")}


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
