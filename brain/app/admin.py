"""The engineer's booth: system status for the owner.

SKELETON, deliberately: every collector is cheap, tolerant, and returns a dict with an
"ok" verdict — a dead icecast must render as a red card, never a 500. The Station
Engineer chat (dj.py-pattern tool loop with ops tools) bolts on later; the status
collectors here become its eyes when it does.

Honest boundary: the brain cannot restart containers — it IS one. Host-level actions
(docker, slab, launchd) stay with slab/ssh; this page observes and advises.
"""
from __future__ import annotations

import os
import shutil
import socket

import httpx

from . import channels, config, db, presence


def _icecast() -> dict:
    """icecast publishes JSON at /status-json.xsl — mounts and listener counts for free."""
    try:
        r = httpx.get(f"{config.ICECAST_ORIGIN}/status-json.xsl", timeout=4)
        r.raise_for_status()
        src = (r.json().get("icestats") or {}).get("source") or []
        if isinstance(src, dict):
            src = [src]
        mounts = [{"mount": s.get("listenurl", "").rsplit("/", 1)[-1],
                   "listeners": s.get("listeners", 0)} for s in src]
        return {"ok": True, "mounts": len(mounts), "detail": mounts}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def _liquidsoap() -> dict:
    """A TCP connect to the telnet port is the cheapest 'is the radio engine alive'."""
    try:
        with socket.create_connection(
                (config.LIQUIDSOAP_HOST, config.LIQUIDSOAP_TELNET_PORT), timeout=3):
            return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def _database() -> dict:
    try:
        members = db.query("SELECT COUNT(*) AS n FROM members")[0]["n"]
        queued = db.query("SELECT COUNT(*) AS n FROM queue WHERE served=0")[0]["n"]
        return {"ok": True, "members": members, "queued_tracks": queued}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def _queues() -> list[dict]:
    try:
        rows = db.query(
            "SELECT channel, COUNT(*) AS unserved FROM queue WHERE served=0 "
            "GROUP BY channel ORDER BY channel")
        return [{"channel": r["channel"], "unserved": r["unserved"]} for r in rows]
    except Exception:
        return []


def _disk() -> dict:
    try:
        u = shutil.disk_usage(config.MUSIC_DIR)
        return {"ok": u.free > 5 * 2**30, "free_gb": round(u.free / 2**30, 1),
                "total_gb": round(u.total / 2**30, 1)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def _channels(icecast: dict) -> dict:
    """Owner curation list: every broadcast channel (mix-only shelf-*/vault-* excluded —
    they cost liquidsoap nothing, there's nothing to take offline), enabled state, and
    CURRENT listener count where a mount exists. Takes the already-fetched icecast result
    so this doesn't make its own redundant HTTP call."""
    try:
        live = {m["mount"].lstrip("/"): m.get("listeners", 0)
                for m in (icecast.get("detail") or [])} if icecast.get("ok") else {}
        rows = channels.list_all_channels()
        for r in rows:
            r["listeners"] = live.get(r["slug"])   # None = not currently mounted
        return {"ok": True, "channels": rows}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def _uploads() -> dict:
    """Contributor uploads via /api/contribute — the 'contributions' ledger, not the
    abandoned jam-contribd host daemon (see AGENTS.md's contributor-path section)."""
    try:
        total = db.query("SELECT COUNT(*) AS n FROM contributions")[0]["n"]
        recent = db.query(
            "SELECT email, slug, folder_name, created_at FROM contributions "
            "ORDER BY id DESC LIMIT 10")
        return {"ok": True, "total": total, "recent": recent}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def _rip() -> dict:
    p = os.path.join(config.MUSIC_DIR, ".rip-status")
    try:
        if not os.path.exists(p):
            return {"ok": True, "state": "idle"}
        return {"ok": True, "state": open(p).read()[:300],
                "age_s": int(os.path.getmtime(p) and (os.stat(p).st_mtime))}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def status() -> dict:
    ls = presence.listeners()
    ic = _icecast()
    return {
        "icecast": ic,
        "liquidsoap": _liquidsoap(),
        "database": _database(),
        "disk": _disk(),
        "rip": _rip(),
        "queues": _queues(),
        "uploads": _uploads(),
        "channels": _channels(ic),
        "listening": ls,
        "online": presence.online(),
        # host-side facts the brain honestly can't see from inside its container:
        "not_visible_from_here": ["backup age (euler pulls)", "slab daemon", "cloudflared tunnel"],
    }
