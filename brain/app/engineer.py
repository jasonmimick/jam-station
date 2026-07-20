"""The Station Engineer: the DJ's tool loop wearing an ops toolbelt.

Same skeleton as dj.py on purpose — one proven loop, two personas. The DJ touches music;
the engineer touches the MACHINERY: status, queues, shelf-station sync, the cover
enricher, the play log. Owner-only at the endpoint (main.py gates it)."""
from __future__ import annotations

import json

import anthropic

from . import admin, channels, config, covers, db, presence

SYSTEM = """You are the Station Engineer of jam-station — a personal internet radio station
running as three containers (brain/FastAPI, liquidsoap, icecast) on the owner's Mac mini
under slab, public through a Cloudflare tunnel. You are terse, competent, and honest.
You speak to the OWNER only.

How the plumbing works, so your diagnoses are real:
- liquidsoap polls the brain's /api/next per channel, crossfades, feeds icecast (one mount
  per broadcast channel). It watches the channel list and RESTARTS ITSELF when the list
  changes (with a 15s hard-exit backstop if graceful shutdown wedges).
- Channels top up their own queues (ensure_queue) when they run low. Archive channels
  queue whole shows; library channels queue random batches; shelf-* genre stations are
  MIX-ONLY — no mount, clients play them as on-demand mixes. An empty queue usually heals
  itself; a queue that STAYS empty means the adapter's source is failing.
- The cover enricher (covers) backfills art/year/genres in the background.
- Presence: radio listeners = open /stream connections; on-demand = heartbeats; open apps
  = recent authenticated API chatter.

Ground rules:
- CHECK BEFORE YOU CLAIM: run station_status (and queue_status for a specific channel)
  before diagnosing anything. Never invent a reading.
- Use tools for real actions when asked (skip, flush, top up, resync shelf stations,
  kick covers). Say what you did and what changed.
- Flushing a queue is safe — it refills itself from the channel's recipe within a minute.
- YOUR HARD BOUNDARY: you run INSIDE the brain container. You cannot restart containers,
  touch docker/slab/launchd, reach the host's disks, or see backups/the tunnel/the slab
  daemon. For host-side problems, say exactly what you'd run and where — e.g. "ssh to the
  mini and run: docker restart slab-jam-radio" — and stop there. Never pretend a host
  action happened.
- If icecast or liquidsoap is down, say so plainly and give the one-line host fix.
"""

TOOLS = [
    {"name": "station_status",
     "description": "Full system status: icecast mounts, liquidsoap liveness, Postgres, disk, ripper, per-channel queues, listeners, open apps.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_channels",
     "description": "Every channel: slug, name, source, playable, private.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "queue_status",
     "description": "One channel's queue: unserved count, upcoming tracks, now playing.",
     "input_schema": {"type": "object", "properties": {"channel": {"type": "string"}},
                      "required": ["channel"]}},
    {"name": "skip_track",
     "description": "Skip the current track on a broadcast channel. Moves the station for every listener.",
     "input_schema": {"type": "object", "properties": {"channel": {"type": "string"}},
                      "required": ["channel"]}},
    {"name": "flush_queue",
     "description": "Clear a channel's unserved queue. It refills itself from the recipe within a minute — safe, and the fix for a queue full of the wrong thing.",
     "input_schema": {"type": "object", "properties": {"channel": {"type": "string"}},
                      "required": ["channel"]}},
    {"name": "topup_queue",
     "description": "Force a queue top-up now instead of waiting for the low-water mark.",
     "input_schema": {"type": "object", "properties": {"channel": {"type": "string"}},
                      "required": ["channel"]}},
    {"name": "resync_shelf_stations",
     "description": "Re-derive the shelf-* genre stations from the record crate (sections >=3 records appear, shrunk ones retire).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "kick_covers",
     "description": "Wake the cover/genre enricher to backfill art, years and sections in the background.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "play_history",
     "description": "Recent play log, optionally for one channel.",
     "input_schema": {"type": "object", "properties": {"channel": {"type": "string"},
                                                       "limit": {"type": "integer"}}}},
]


def _run_tool(name: str, args: dict) -> dict | list:
    if name == "station_status":
        return admin.status()
    if name == "list_channels":
        return [{"slug": c["slug"], "name": c["name"], "source": c["source"],
                 "playable": c.get("playable", True), "private": c.get("private", False)}
                for c in channels.list_channels()]
    if name == "queue_status":
        return channels.queue_status(args["channel"])
    if name == "skip_track":
        return {"skipped": channels.skip(args["channel"])}
    if name == "flush_queue":
        n = channels.clear_queue(args["channel"])
        return {"cleared": n, "note": "refills itself from the recipe within a minute"}
    if name == "topup_queue":
        return {"added": channels.ensure_queue(args["channel"])}
    if name == "resync_shelf_stations":
        channels.sync_genre_channels()
        return {"shelf": [c["slug"] for c in channels.list_channels()
                          if c["slug"].startswith("shelf-")]}
    if name == "kick_covers":
        covers.kick()
        return {"kicked": True}
    if name == "play_history":
        limit = max(1, min(int(args.get("limit") or 20), 100))
        if args.get("channel"):
            return db.query("SELECT channel, title, artist, played_at FROM history "
                            "WHERE channel=? ORDER BY id DESC LIMIT ?",
                            (args["channel"], limit))
        return db.query("SELECT channel, title, artist, played_at FROM history "
                        "ORDER BY id DESC LIMIT ?", (limit,))
    return {"error": f"no such tool {name!r}"}


def chat(messages: list[dict]) -> str:
    """Same loop as dj.chat — see there for the shape."""
    client = anthropic.Anthropic()
    convo = [{"role": m["role"], "content": m["content"]} for m in messages]

    for _ in range(8):
        resp = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1500,
            system=SYSTEM,
            tools=TOOLS,
            messages=convo,
        )
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")

        convo.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            try:
                out = _run_tool(block.name, block.input or {})
                payload = json.dumps(out, default=str)[:20000]
            except Exception as e:
                payload = json.dumps({"error": str(e)})
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": payload})
        convo.append({"role": "user", "content": results})

    return "Lost the thread in the machine room (tool loop limit) — ask again?"
