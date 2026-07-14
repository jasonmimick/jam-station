"""The AI DJ: Anthropic tool-calling loop over the station's controls."""
from __future__ import annotations

import json
import re

import anthropic

from . import channels, config
from .adapters import archive, cc, library, phishin

SYSTEM = """You are the DJ of jam-station, a personal internet radio station running on the
owner's Mac mini. You are warm, knowledgeable, and a little bit of a music nerd — deep
lore on the Grateful Dead, jam bands, jazz, and 70s fusion.

The station has channels. Each channel is a saved recipe the station keeps topped up:
- source "archive": pulls live shows from archive.org's Live Music Archive (taper-friendly
  bands only: Grateful Dead, Umphrey's McGee, moe., Disco Biscuits, String Cheese, Widespread
  Panic, Goose, Medeski Martin & Wood, and many more). Community avg_rating lets you pick the
  GOOD tapes — use min_rating and 'avg_rating desc' sorting. Note: Phish is NOT on the
  Archive (band restricts it) — Phish lives on its own "phishin" source. Commercial 70s
  fusion (Weather Report, Mahavishnu, RTF) isn't on the Archive either — that lives in
  the owner's own library channel.
- source "phishin": pulls Phish shows from phish.in. Community likes_count is the quality
  signal. Show identifiers are dates (YYYY-MM-DD). The seeded "phish" channel plays the
  most-liked tapes; make era channels with a year in the query.
- source "library": plays the owner's own files from the music/ folder.
- source "cc": Creative-Commons / public-domain audio from the WHOLE Internet Archive —
  NOT the Live Music Archive. This is how you play anything outside the jam-band world:
  ragtime, danish folk, gamelan, klezmer, chiptune, field recordings, classical. The query
  Use search_cc with a vibe ("ragtime", "danish folk", "bach") to FIND candidates — then
  READ what came back, judge it, and create the channel with query.items = [the exact
  identifiers you actually believe in]. create_channel REFUSES a cc channel without items,
  and it is right to: a search for "ragtime" returns an ambient album called "Elemental
  Ragtime", and a search for "bach" returns the piano music of Sorabji. Matching a word is
  not matching a genre. Every item must carry an explicit licence, or we don't play it.

What you can do with tools: search the Archive and phish.in, inspect a show's tracklist,
queue a specific show on a channel (optionally clearing what's queued), check what's
playing/upcoming, skip the current track, and create brand-new channels from a vibe.

Ground rules:
- When asked to play something, actually queue it with tools — don't just talk about it.
- Prefer highly-rated tapes; mention the venue/date like a real DJ would.
- New channels go on air by themselves within ~30 seconds — the radio engine notices the
  new channel and reloads to open its mount. NEVER tell the owner to restart anything.
- ALWAYS prove a channel can play before you create it: run search_shows / search_phish_shows
  / search_cc first. create_channel will reject a query that returns NOTHING.
- BUT "it returned rows" IS NOT "it returned the RIGHT MUSIC". This is the mistake to avoid:
  * READ the titles and creators that come back. Judge them. Are they actually the thing the
    owner asked for? A search for "danish folk" that returns a CC mixtape and a noise album
    is a FAILED search, even though it returned rows.
  * If the results are not the genre/artist asked for, DO NOT create the channel. Say plainly
    that the music isn't there, and offer the nearest thing you CAN actually play.
  * Get the RIGHT one. Archive collection names are exact and unobvious — Goose is
    'GooseBand', not 'Goose'. A plausible-looking name that returns the wrong band (or an
    empty set) is worse than admitting you couldn't find it. Verify with a search, look at
    what came back, and confirm it is the artist you meant.
  * Never name a channel after music it does not actually contain.
- Only those four sources exist, and you cannot conjure music that isn't in one of them.
  The Archive ("archive") is taper-friendly LIVE tapes (jam bands). Commercial studio
  catalogue — bebop (Parker, Dizzy), Weather Report, Mahavishnu, most jazz and rock records —
  is NOT there and never will be. For anything outside jam bands, reach for "cc" first: it
  covers ragtime, folk, world, classical and more, but only material that is explicitly
  licensed to be shared. Famous commercial recordings will NOT be in "cc" either — you'll
  find CC performances and public-domain material, not the hit records. Say so plainly
  rather than promising a name you can't deliver. Anything else needs the owner's own
  library, and only if the files actually exist.
  A "library" channel with no files is a silent, dead channel, and create_channel will
  refuse to make one. If a request can't be sourced, SAY SO plainly and offer the closest
  thing you can actually play. Never claim a channel is ready when it has no music.
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
        "name": "search_phish_shows",
        "description": ("Search phish.in for Phish shows. Returns date (the identifier), "
                        "venue, tour, likes_count. Sort 'likes_count:desc' finds the "
                        "classics; add year to browse an era."),
        "input_schema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "rows": {"type": "integer", "default": 20},
                "sort": {"type": "string", "default": "likes_count:desc"},
            },
        },
    },
    {
        "name": "search_cc",
        "description": ("Search Creative-Commons / public-domain audio across the whole "
                        "Internet Archive by free text (a vibe: 'ragtime', 'danish folk', "
                        "'klezmer'). Returns identifier, title, creator, licence. Use this "
                        "BEFORE creating a 'cc' channel so you know it returns real music."),
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "free text, e.g. 'ragtime piano'"},
                "rows": {"type": "integer", "default": 20},
            },
            "required": ["search"],
        },
    },
    {
        "name": "get_show",
        "description": ("Get one show's metadata and tracklist. Pass an archive.org "
                        "identifier, or a YYYY-MM-DD date for a Phish show."),
        "input_schema": {
            "type": "object",
            "properties": {"identifier": {"type": "string"}},
            "required": ["identifier"],
        },
    },
    {
        "name": "play_show",
        "description": ("Queue a specific show on a channel. Use an archive.org identifier "
                        "for archive channels, a YYYY-MM-DD date for phishin channels. "
                        "clear=true plays it next (clears the unplayed queue), "
                        "clear=false appends."),
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
                        "collections[], year, min_rating, free_text, sort. source 'phishin' "
                        "query supports: year, sort, rows. source 'library' query supports: "
                        "folders[] (subfolders of music/). source 'cc' query supports: "
                        "search (FREE TEXT — a vibe like 'ragtime' or 'danish folk'), year."),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "url-safe, e.g. 'spring90'"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "source": {"type": "string", "enum": ["archive", "phishin", "library", "cc"]},
                "query": {"type": "object"},
            },
            "required": ["slug", "name", "source", "query"],
        },
    },
]


def _cc_has_tracks(identifier: str) -> bool:
    try:
        return bool(cc.get_show(identifier).get("tracks"))
    except Exception:
        return False


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
    if name == "search_cc":
        return [
            {"identifier": d.get("identifier"), "title": d.get("title"),
             "creator": d.get("creator"), "licence": d.get("licenseurl")}
            for d in cc.search_items(search=args["search"], rows=args.get("rows", 20))
        ][:20]
    if name == "search_phish_shows":
        return phishin.search_shows(
            year=args.get("year"),
            rows=args.get("rows", 20),
            sort=args.get("sort", "likes_count:desc"),
        )[:25]
    if name == "get_show":
        ident = args["identifier"]
        adapter = phishin if re.fullmatch(r"\d{4}-\d{2}-\d{2}", ident) else archive
        show = adapter.get_show(ident)
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
        source, query = args["source"], args["query"]
        # A channel whose query yields nothing is a station that broadcasts silence.
        # Prove it can produce at least one track BEFORE creating it — the prompt
        # alone won't reliably stop the DJ announcing a station that can't play.
        if source == "library" and not library.pick_tracks(query, count=1):
            folders = ", ".join(query.get("folders") or []) or "music/"
            return {"error": f"no audio files under music/{folders} — this channel would be "
                             f"silent. Say plainly that you cannot source this music: it is "
                             f"not on the Archive (live tapes only) and the owner's library "
                             f"has no such files. Do NOT claim the channel is ready."}
        if source == "archive" and not archive.search_shows(
                collections=query.get("collections"), free_text=query.get("free_text"),
                year=query.get("year"), min_rating=query.get("min_rating"), rows=1):
            return {"error": "that Archive query returns no shows — the collection name is "
                             "probably wrong (e.g. Goose is 'GooseBand', not 'Goose'). Run "
                             "search_shows to find a query that actually returns tapes, then "
                             "try again. Do NOT claim the channel is ready."}
        if source == "cc":
            # A free-text cc channel CANNOT be trusted, and we have the scars to prove it: a
            # search for "ragtime" returned an ambient noise album called "Elemental Ragtime",
            # and a search for "bach" returned the piano music of SORABJI. The query matched a
            # word; the music was wrong. Telling the DJ to be careful did not work — so the
            # tool now refuses. Search to FIND candidates, curate to SHIP them.
            items = query.get("items") or []
            if not items:
                return {"error": "cc channels must be CURATED, not searched. Run search_cc, "
                                 "READ the titles and creators it returns, decide which ones "
                                 "are genuinely the music asked for, and pass those exact "
                                 "identifiers as query.items = [...]. A free-text cc query "
                                 "matches a WORD, not a GENRE: 'ragtime' returns an ambient "
                                 "album called 'Elemental Ragtime', and 'bach' returns the "
                                 "piano music of Sorabji. If nothing you find is actually the "
                                 "music asked for, say so plainly and create nothing."}
            if not any(_cc_has_tracks(i) for i in items[:4]):
                return {"error": "none of those identifiers have playable audio. Check them "
                                 "with get_show. Do NOT claim the channel is ready."}
        if source == "phishin" and not phishin.search_shows(
                year=query.get("year"), rows=1, sort=query.get("sort", "likes_count:desc")):
            return {"error": "that phish.in query returns no shows. Check it with "
                             "search_phish_shows first. Do NOT claim the channel is ready."}
        ch = channels.create_channel(args["slug"], args["name"],
                                     args.get("description", ""), source, query)
        return {"created": ch,
                "note": "on air within ~30s — the radio engine reloads itself. "
                        "Do not tell the owner to restart anything."}
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
