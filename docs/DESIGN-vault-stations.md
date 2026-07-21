# DESIGN — Vault Stations (streaming the attic music library)

**Status:** BUILD IN PROGRESS — spec finalized 2026-07-20 (was: designed + paused earlier same day).
**Goal:** turn the ~65 GB of personal music archived on the Time Capsule vault into stations
on jam-station, **without copying it onto the mini** (there isn't room) — and do it behind a
contract that anyone else's machine can implement later (the extensibility story).

This is the **Sourcing** layer for a big local archive — the "attic source adapter"
AGENTS.md §Family/affiliate promised. (Carriage — a family member's whole station relayed
onto your dial — is a separate layer, still coming.)

---

## The problem, precisely

- The vault music lives on the **AFP-mounted Time Capsule**, visible only to the mini's **host
  OS** at `/tmp/tc-afp/attic-vault/` (AFP, not SMB — 9× faster). Structure is artist-organized:
  `drive-03-inesse-reco/Music/<Artist>/<Album>/<tracks>` (~345 artists, ~38 GB) and
  `drive-08-hm500-win/…` (~27 GB music).
- The **jam-brain container** streams from its own docker volume. It **cannot see the TC** —
  the AFP mount lives on macOS and does not propagate into the Linux docker VM.
- The mini has **~22 GB free** vs ~65 GB of music — copying it in is not an option.

So streaming requires a bridge: something on the host (which can read the vault) serving the
files to the container over HTTP.

## The shelf-server contract — this is the product

Three endpoints. Anything that speaks them can feed stations (the TC vault today; dad's Mac
over the tailnet tomorrow):

```
GET /catalog.json   {"categories": ["Jazz", "Rock", …],
                     "tracks": [{root, path, artist, album, title, genres, url}]}
GET /file/<root>/<path>    the bytes — single-range HTTP Range, ../-escape guarded
GET /health                {ok, roots: {id: {present, files}}}
```

- `categories` = the sections THIS shelf wants as channels — a server-side decision; each
  attic says what categories it wants on the dial.
- `url` is the ready-made `/file/<root>/<quoted-path>` path; the brain only prefixes the
  server origin. The server owns its URL format.
- A missing root (TC unmounted) degrades to an empty catalog + `present: false` — stations
  go OFF AIR, never break.

## The pieces

```
  TC vault (AFP)                    mini host                         jam-brain container
  /tmp/tc-afp/attic-vault  ──────►  attic-server.py (stdlib http) ◄──  adapters/attic.py
   Artist/Album/track.mp3           :8517, launchd-managed             (source="attic")
                                    _genres.json per root              via host.docker.internal:8517
```

### 1. `tools/attic-server.py` (host, stdlib only)
- `ThreadingHTTPServer`; env config `ATTIC_ROOTS` (`rootid=path` pairs, comma-sep) and
  `ATTIC_PORT` (default 8517). Binds 0.0.0.0 — container via `host.docker.internal`, tailnet
  via `100.91.29.30`. **NEVER exposed through the Cloudflare tunnel** — this is private music.
- Catalog walk: artist = first dir under root, album = second; title = filename stem, leading
  track number stripped, `Artist - Title` split honored (same conventions as `library._meta`;
  the path IS the tags). Skips `._*` AppleDouble + hidden files. In-memory cache, re-walk on
  ~15 min TTL or `?refresh=1`.
- **Genres**: per-root sidecar `_genres.json` (`{"Artist Name": ["Jazz", …]}` — artist-level;
  the vault has no track metadata). Server stamps each track's `genres` from it;
  `categories` = union of genres present (or explicit `ATTIC_CATEGORIES` env to curate).
- `tools/attic-genres.py`: one-shot enrichment — MusicBrainz artist lookup → tags → the same
  BUCKETS covers.py uses → `_genres.json`. ~345 artists at 1 req/s ≈ 6 min. Only fills blanks;
  the owner's hand-edits are never overwritten.
- `tools/mini/run.attic.server.plist` — launchd, KeepAlive (the `run.jam.inbox.plist` pattern).

### 2. `brain/app/adapters/attic.py` (remote-URL pattern, mirror of archive.py)
- `config.ATTIC_SERVER_URL` (default `""` → adapter returns `[]`; stations honestly
  unplayable until configured).
- Catalog cached ~300 s, ~60 s negative cache when unreachable (so a flap can't spam).
- `pick_tracks(cfg, count)` query forms:
  - `{"all": true}` — everything (**The Vault**, mounted broadcast channel)
  - `{"spotlight": true}` — ONE random artist per top-up (**Artist Spotlight**, mounted)
  - `{"artist": "…"}` — case-insensitive artist match
  - `{"genre": "Jazz"}` — the category channels (MIX-ONLY, like shelf-*)
- `build_mix(genre, count)` — twin of `library.build_mix`, for the mix endpoint.
- Registered in `STREAMABLE_SOURCES`; `_enqueue_attic()` mirrors `_enqueue_library()`;
  **`PRIVATE_SOURCES = {"library", "attic"}`** drives both `list_channels()` privacy and the
  `/stream/<slug>` member gate. Tests mock the catalog per conftest.

### 3. Category channels + the generic mix endpoint
- `channels.sync_attic_channels()` (patterned on `sync_genre_channels`): each declared
  category with enough tracks → upsert `vault-<slug>` (`query={"genre": name}`); retired when
  the category vanishes. Runs at startup. The existing `streamable_only` genre filter keeps
  them out of channels.liq — **mix-only for free, zero new liquidsoap mounts/CPU**.
- New `GET /api/mix?slug=<channel>&count=` dispatches by the channel's source (library or
  attic) and returns the same show-shaped mix as `/api/library/mix` (kept for back-compat —
  Session uses it). The web UI's mix machinery carries the slug instead of a bare genre.

## Why this shape
- **No copy, no giant mini disk.** Only bytes for what's *playing* move.
- **Reuses everything downstream.** Tracks become annotate-URIs; liquidsoap + icecast +
  on-demand + the dial all work unchanged. Category channels reuse the shelf's mix machinery.
- **Host boundary is honest.** The one thing containers can't do (read an AFP mount) is the
  one thing the host server does — same split as CD ripping.
- **The contract is the extension point.** One adapter, N shelf servers; a new source of
  music is a config row, not new code.

## Build checklist
- [ ] `tools/attic-server.py` + `run.attic.server.plist`, verify `/catalog.json` on the mini
- [ ] `tools/attic-genres.py` → `_genres.json`, verify categories appear in the catalog
- [ ] `brain/app/adapters/attic.py` + channels/main wiring + `/api/mix` + web UI tune + tests
- [ ] container→host reach confirmed; `ATTIC_SERVER_URL` set on jam-brain; deploy
- [ ] create **The Vault** + **Artist Spotlight**; `vault-*` category channels sync at boot
- [ ] verify: private on the dial, channels.liq stable (exactly +2 lines once), audio plays
- [ ] AGENTS.md updated (adapter built, contract, env var, flap gotcha)
- [ ] drive-08's Music root added once drive-03 works

## Open items
- AFP mount doesn't survive reboot (launchd mount TODO — separate from this build; the
  server degrades to empty catalog / OFF AIR meanwhile).
- Session apps: vault category mixes not wired yet (they keep using `/api/library/mix` for
  shelf sections; `/api/mix` adoption is a later Session task).
- Decade stations: need year metadata — a later enrichment pass.

## Fast fallback (unchanged)
Copy a curated ~15 GB slice into `/music/cds/` and it becomes `library` stations with zero
new code. Stopgap only — the shelf-server path is the real answer.
