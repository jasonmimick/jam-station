# AGENTS.md — guide for AI coding agents working on jam-station

This is the canonical agent guide. `CLAUDE.md` and `.github/copilot-instructions.md`
point here. Keep all three in sync by editing only this file.

## What this project is

A personal, multi-channel internet radio station for one person and a couple of
friends. It runs in Docker on a Mac mini, streams over the owner's Tailscale tailnet
(never the public internet), and uses an AI DJ (Claude tool-calling) to find and queue
live shows from the Internet Archive's Live Music Archive. Personal use only — never
add features that download from, or rebroadcast, DRM'd/subscription sources
(Spotify, Apple Music, YouTube audio). Those services are integrated *playlist-only*:
the AI curates via their official APIs, their native apps play.

## Architecture in one paragraph

`brain` (FastAPI, `brain/app/`) is the only custom service. It owns channel
definitions (SQLite), searches archive.org (community `avg_rating` is the quality
signal), runs the Claude tool loop (`dj.py`), and serves the web UI. `liquidsoap`
(`liquidsoap/radio.liq`) polls `GET /api/next?channel=<slug>` per channel, crossfades,
and feeds `icecast` (one mount per channel). `navidrome` serves the owner's own files.
Everything is wired in `docker-compose.yml`.

## Layout

```
brain/app/main.py            FastAPI routes (thin — logic lives elsewhere)
brain/app/channels.py        channel manager: seeds, queue top-up, next_track, prefetch
brain/app/dj.py              AI DJ: system prompt, TOOLS schema, tool loop
brain/app/adapters/          one module per audio source (archive.py, library.py)
brain/app/db.py              sqlite helpers (query/execute) — no ORM, keep it that way
brain/app/static/index.html  the whole web UI (single file, vanilla JS, no build step)
brain/tests/                 pytest; conftest.py mocks archive.org via httpx.MockTransport
liquidsoap/radio.liq         radio engine config (liquidsoap 2.2.x)
docs/architecture.html       the system diagram (update it if you change the shape)
```

## Commands

```bash
cd brain
pip install -r requirements-dev.txt
pytest                                  # must pass; no network needed (archive mocked)
uvicorn app.main:app --reload --port 8080

# validate liquidsoap changes (apt liquidsoap 2.2.x works; image pins v2.2.5):
liquidsoap --check liquidsoap/radio.liq   # warnings ok; errors are not
# note: --check also RUNS top-level code; with no brain reachable the script
# intentionally exits 1 via shutdown(). Type errors print messages; exit 1 alone
# with no output usually just means "brain not running".

docker compose up -d --build            # full stack (on the mac mini)
```

## Conventions

- **Keep dependencies minimal.** Runtime deps are fastapi, uvicorn, httpx, anthropic.
  Don't add an ORM, a task queue, or a frontend framework. sqlite3 + threads is enough
  for a one-listener station.
- **Adapters are the extension point.** A new audio source = a new module in
  `brain/app/adapters/` exposing track dicts (`url`, `title`, `artist`, `album`),
  plus a `source` value handled in `channels.ensure_queue()`. Look at `library.py`
  for the minimal shape.
- **New DJ abilities** = add a tool schema to `TOOLS` in `dj.py`, a branch in
  `_run_tool()`, and keep tool results JSON-serializable and truncated (see existing
  20k cap).
- **Tests mock the network.** archive.org is unreachable from CI/sandboxes; extend the
  `httpx.MockTransport` handler in `tests/conftest.py` rather than hitting the real API.
  Every new endpoint/adapter needs a test.
- **The web UI stays a single static file** with vanilla JS — it must work from a
  phone browser with no build step.
- **`/api/next` returns `annotate:` URIs.** Titles/quotes are escaped in
  `channels._annotate()`; if you touch metadata, keep double quotes out of values.

## Gotchas

- Queue top-ups are guarded by per-channel `threading.Lock`s (`channels._lock_for`) —
  liquidsoap can poll while a background top-up runs. Don't remove the non-blocking
  acquire or two top-ups will double-queue a show.
- Archive channels enqueue **whole shows** (sets play in order — intentional radio
  feel). Library channels enqueue random batches. Preserve that distinction.
- Channels created at runtime (by the DJ) only get an Icecast mount after
  `docker compose restart liquidsoap` — radio.liq fetches the channel list at startup.
  The DJ's system prompt tells the owner this; keep that true if you change it.
- Phish is not on the Archive (band policy) and commercial 70s fusion isn't either.
  Don't "fix" empty search results for those by loosening queries — they need their
  own adapters (phish.in) or the owner's library.
- liquidsoap is pinned to `savonet/liquidsoap:v2.2.5`. Its scripting language breaks
  between minor versions — if you bump the pin, re-run `liquidsoap --check` and expect
  syntax churn (`http.get` response coercion, `try/catch`, source methods).
- The docker registry may be unreachable in sandboxes; apt's liquidsoap 2.2.4 is close
  enough for `--check`.

## Roadmap (safe next tasks)

1. phish.in adapter (free API, audio URLs — fits the archive.py shape)
2. Spotify/YouTube *playlist* adapters (curate-only: write playlists via API; never audio)
3. TTS DJ intros: generate a short spoken intro when a new show starts, insert via
   liquidsoap `request.queue` jingle source
4. "On this day" channel: archive search with `date:*-MM-DD` style free_text
5. Play-history page in the web UI (`/api/history` already exists)
