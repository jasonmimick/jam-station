#!/usr/bin/env python3
"""attic-server — the shelf server: serves vault music to jam-station over HTTP.

Runs on the MINI HOST (launchd, run.attic.server.plist) because only the host can see
the AFP-mounted Time Capsule; the jam-brain container reaches it at
http://host.docker.internal:8517. Stdlib only — must run on a bare Mac.

The contract (anything that speaks it can feed stations — this is the extension point):

    GET /catalog.json   {"categories": [...], "tracks": [{root, path, artist, album,
                                                          title, genres, url}]}
    GET /file/<root>/<path>    the audio bytes (single-range HTTP Range for seeking)
    GET /health                {ok, roots: {id: {present, files}}}

Config by env:
    ATTIC_ROOTS       rootid=path pairs, comma-separated. e.g.
                      drive03=/tmp/tc-afp/attic-vault/drive-03-inesse-reco/Music
    ATTIC_PORT        default 8517
    ATTIC_CATEGORIES  optional comma-sep curation of which genres become channels;
                      default = every genre present in the _genres.json sidecars

Genres are artist-level, from a per-root `_genres.json` sidecar written by
attic-genres.py (or by hand): {"Artist Name": ["Jazz", ...]}. The vault has no
track metadata — the path IS the tags, like the brain's library adapter.

A missing root (TC unmounted) degrades to an empty catalog and present:false in
/health — vault stations go OFF AIR, they never break. NEVER expose this port
through the Cloudflare tunnel: it is the owner's private music.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("ATTIC_PORT", "8517"))
CATALOG_TTL = 15 * 60
AUDIO_EXTENSIONS = (".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wav")
GENRES_FILE = "_genres.json"


def parse_roots(spec: str) -> dict[str, str]:
    roots = {}
    for part in (spec or "").split(","):
        rootid, sep, path = part.strip().partition("=")
        if sep and rootid and path:
            roots[rootid] = path
    return roots


ROOTS = parse_roots(os.environ.get("ATTIC_ROOTS", ""))
CATEGORIES_ENV = [c.strip() for c in os.environ.get("ATTIC_CATEGORIES", "").split(",") if c.strip()]

_TRACK_NUM = re.compile(r"^(\d{1,3})[ .\-_]+(.+)$")


def _title_artist(stem: str, dir_artist: str) -> tuple[str, str]:
    """Filename stem -> (title, artist). Same conventions as the brain's library._meta:
    strip a leading track number FIRST, then honor an 'Artist - Title' split; otherwise
    the folder's artist owns the track."""
    m = _TRACK_NUM.match(stem)
    core = (m.group(2) if m else stem).strip()
    artist, sep, title = core.partition(" - ")
    if sep:
        return title.strip(), artist.strip()
    return core, dir_artist


def _walk_root(rootid: str, root: str) -> list[dict]:
    genres_by_artist = {}
    try:
        with open(os.path.join(root, GENRES_FILE)) as f:
            genres_by_artist = {k.lower(): v for k, v in json.load(f).items()}
    except Exception:
        pass
    tracks = []
    for dirpath, dirs, files in os.walk(root):
        dirs.sort()
        for fn in sorted(files):
            if fn.startswith(("._", ".")) or not fn.lower().endswith(AUDIO_EXTENSIONS):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            parts = rel.split(os.sep)
            artist = parts[0] if len(parts) > 1 else ""
            album = parts[1] if len(parts) > 2 else ""
            title, t_artist = _title_artist(os.path.splitext(fn)[0], artist)
            tracks.append({
                "root": rootid,
                "path": rel,
                "artist": t_artist,
                "album": album,
                "title": title,
                "genres": genres_by_artist.get(artist.lower(), []),
                # percent-encode: filenames hold spaces, urls cannot (quote leaves "/" alone)
                "url": f"/file/{rootid}/{urllib.parse.quote(rel)}",
            })
    return tracks


_cache: dict = {"at": 0.0, "catalog": None}
_cache_lock = threading.Lock()


def catalog(refresh: bool = False) -> dict:
    with _cache_lock:
        fresh = _cache["catalog"] is not None and time.time() - _cache["at"] < CATALOG_TTL
        if fresh and not refresh:
            return _cache["catalog"]
    tracks = []
    for rootid, root in ROOTS.items():
        if os.path.isdir(root):
            try:
                tracks += _walk_root(rootid, root)
            except OSError:
                pass                      # a root died mid-walk: serve what we have
    if CATEGORIES_ENV:
        categories = CATEGORIES_ENV
    else:
        categories = sorted({g for t in tracks for g in t["genres"]})
    cat = {"categories": categories, "tracks": tracks}
    with _cache_lock:
        _cache.update(at=time.time(), catalog=cat)
    return cat


def resolve_file(rootid: str, relpath: str) -> str | None:
    """A /file url -> a real path inside its root, or None. Guarded like the brain's
    /music route: realpath, then require the root prefix — no ../ escapes."""
    root = ROOTS.get(rootid)
    if not root:
        return None
    base = os.path.realpath(root)
    full = os.path.realpath(os.path.join(base, relpath))
    if not full.startswith(base + os.sep):
        return None
    return full if os.path.isfile(full) else None


_MIME = {".mp3": "audio/mpeg", ".flac": "audio/flac", ".ogg": "audio/ogg",
         ".m4a": "audio/mp4", ".aac": "audio/aac", ".opus": "audio/opus",
         ".wav": "audio/wav"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "attic-server/1"

    def log_message(self, fmt, *args):     # one line per request, no reverse DNS
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                      # noqa: N802 (http.server API)
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/health":
                roots = {rid: {"present": os.path.isdir(p)} for rid, p in ROOTS.items()}
                cat = _cache["catalog"]
                for rid in roots:
                    roots[rid]["files"] = sum(
                        1 for t in (cat["tracks"] if cat else []) if t["root"] == rid)
                return self._json({"ok": True, "roots": roots})
            if parsed.path == "/catalog.json":
                refresh = "refresh" in urllib.parse.parse_qs(parsed.query)
                return self._json(catalog(refresh=refresh))
            if parsed.path.startswith("/file/"):
                return self._file(parsed.path)
            return self._json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass                           # listener hung up mid-stream; normal for audio

    def _file(self, path: str) -> None:
        rest = path[len("/file/"):]
        rootid, sep, rel = rest.partition("/")
        full = resolve_file(rootid, urllib.parse.unquote(rel)) if sep else None
        if not full:
            return self._json({"error": "no such file"}, 404)
        size = os.path.getsize(full)
        mime = _MIME.get(os.path.splitext(full)[1].lower(), "application/octet-stream")

        start, end = 0, size - 1
        rng = self.headers.get("Range", "")
        m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
        partial = bool(rng) and bool(m) and (m.group(1) or m.group(2))
        if partial:
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
            else:                          # suffix form: bytes=-N (the last N bytes)
                start = max(0, size - int(m.group(2)))
            if start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", mime)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(full, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1 << 16, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def main() -> None:
    if not ROOTS:
        print("attic-server: ATTIC_ROOTS is empty — serving an empty catalog", flush=True)
    for rid, p in ROOTS.items():
        print(f"attic-server: root {rid} = {p} ({'present' if os.path.isdir(p) else 'MISSING'})",
              flush=True)
    threading.Thread(target=catalog, daemon=True).start()   # warm the cache off the boot path
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"attic-server: listening on :{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
