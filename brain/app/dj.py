"""The AI DJ: Anthropic tool-calling loop over the station's controls."""
from __future__ import annotations

import json

import anthropic

from . import channels, config
from .adapters import archive

SYSTEM = """You are the DJ of jam-station, a personal internet radio station running on the
owner's Mac mini. You are warm, knowledgeable, and a little bit of a music nerd — deep
lore on the Grateful Dead, jam bands, jazz, and 70s fusion.

The station has channels. Each channel is a saved recipe the station keeps topped up:
- source "archive": pulls live shows from archive.org's Live Music Archive (taper-friendly
  bands only: Grateful Dead, Umphrey's McGee, moe., Disco Biscuits, String Cheese, Widespread
  Panic, Goose, Medeski Martin & Wood, and many more). Community avg_rating lets you pick the
  GOOD tapes — use min_rating and 'avg_rating desc' sorting. Note: Phish is NOT on the
  Archive (band restricts it), and commercial 70s fusion (Weather Report, Mahavishnu, RTF)
  is not there either — that lives in the owner's own library channel.
- source "library": plays the owner's own files from the music/ folder.

What you can do with tools: search the Archive, inspect a show's tracklist, queue a specific
show on a channel (optionally clearing what's queued), check what's playing/upcoming, skip
the current track, and create brand-new channels from a vibe.

Ground rules:
- When asked to play something, actually queue it with tools — don't just talk about it.
- Prefer highly-rated tapes; mention the venue/date like a real DJ would.
- Newly created channels start streaming after liquidsoap restarts
  (`docker compose restart liquidsoap`) — tell the owner when that's needed.
- Keep replies short and radio-friendly. You're on the air.
"""

TOOLS = [
    {
        "name": "list_channels",
        "description": "List all channels with their source and config.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_shows",
        "description": ("Search the Live Music Archive for shows. Returns identifier, date, "
                        "venue, avg_rating, num_reviews. Use collections like 'GratefulDead', "
                        "'UmphreysMcGee', 'MedeskiMartinandWood'."),
        "input_schema": {
            "type": "object",
            "properties": {
                "collections": {"type": "array", "items": {"type": "string"}},
                "free_text": {"type": "string", "description": "extra solr query text, e.g. venue name"},
                "year": {"type": "integer"},
                "min_rating": {"type": "number"},
                "rows": {"type": "integer", "default": 20},
                "sort": {"type": "string", "default": "avg_rating desc"},
            },
        },
    },
    {
        "name": "get_show",
        "description": "Get one show's metadata and tracklist by archive.org identifier.",
        "input_schema": {
            "type": "object",
            "properties": {"identifier": {"type": "string"}},
            "required": ["identifier"],
        },
    },
    {
        "name": "play_show",
        "description": ("Queue a specific Archive show on a channel. clear=true plays it next "
                        "(clears the unplayed queue), clear=false appends."),
        "input_schema": {
            "type": "object",
            "properties": {
                "channel": {"type": "string"},
                "identifier": {"type": "string"},
                "clear": {"type": "boolean", "default": True},
            },
            "required": ["channel", "identifier"],
        },
    },
    {
        "name": "queue_status",
        "description": "Now playing + upcoming tracks for a channel.",
        "input_schema": {
            "type": "object",
            "properties": {"channel": {"type": "string"}},
            "required": ["channel"],
        },
    },
    {
        "name": "skip_track",
        "description": "Skip the currently playing track on a channel.",
        "input_schema": {
            "type": "object",
            "properties": {"channel": {"type": "string"}},
            "required": ["channel"],
        },
    },
    {
        "name": "create_channel",
        "description": ("Create (or overwrite) a channel. source 'archive' query supports: "
                        "collections[], year, min_rating, free_text, sort. source 'library' "
                        "query supports: folders[] (subfolders of music/)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "url-safe, e.g. 'spring90'"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "source": {"type": "string", "enum": ["archive", "library"]},
                "query": {"type": "object"},
            },
            "required": ["slug", "name", "source", "query"],
        },
    },
]


def _run_tool(name: str, args: dict) -> dict | list:
    if name == "list_channels":
        return channels.list_channels()
    if name == "search_shows":
        docs = archive.search_shows(
            collections=args.get("collections"),
            free_text=args.get("free_text"),
            year=args.get("year"),
            min_rating=args.get("min_rating"),
            rows=args.get("rows", 20),
            sort=args.get("sort", "avg_rating desc"),
        )
        return docs[:25]
    if name == "get_show":
        show = archive.get_show(args["identifier"])
        show["tracks"] = show["tracks"][:40]
        return show
    if name == "play_show":
        n = channels.enqueue_show(args["channel"], args["identifier"],
                                  clear=args.get("clear", True))
        if args.get("clear", True):
            channels.skip(args["channel"])  # jump to the new show now
        return {"queued_tracks": n}
    if name == "queue_status":
        return channels.queue_status(args["channel"])
    if name == "skip_track":
        return {"skipped": channels.skip(args["channel"])}
    if name == "create_channel":
        ch = channels.create_channel(args["slug"], args["name"],
                                     args.get("description", ""),
                                     args["source"], args["query"])
        return {"created": ch,
                "note": "restart liquidsoap to open this channel's stream mount"}
    return {"error": f"unknown tool {name}"}


def chat(messages: list[dict]) -> str:
    """Run the tool loop. `messages` is [{'role': 'user'|'assistant', 'content': str}, ...]."""
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
            except Exception as e:  # tool errors go back to the model
                payload = json.dumps({"error": str(e)})
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": payload})
        convo.append({"role": "user", "content": results})

    return "I got lost in the record crates (tool loop limit) — try that again?"
