# ⚡ jam-station

A personal, multi-channel internet radio station that runs on a Mac mini at home.
An AI DJ (Claude) digs through the Internet Archive's **Live Music Archive** — Grateful
Dead, Umphrey's McGee, moe., MMW and every other taper-friendly band — queues the
well-rated tapes, and streams them as real radio channels you can tune into from the
car over **Tailscale**.

Just for me and a couple friends. Not for sale, not for broadcast.

## What you get

- **Channels like a radio dial** — each one a saved recipe the station keeps topped up:
  `dead77`, `jam`, `latenight-jazz` (all Archive-backed), and `fusion` (your own files).
- **An AI DJ you chat with** — "play a great '77 Dead show", "make me a Spring '90 channel",
  "what's this song?" It searches the Archive by community rating and actually queues things.
- **Real streams** — one Icecast mount per channel. Any radio app, browser, or CarPlay
  client can tune in at `http://<macmini>:8000/<channel>`.
- **Your own library** — Navidrome serves the music you own (the 70s fusion the Archive
  doesn't have) with polished mobile/CarPlay apps and offline caching.

## Architecture

See [`docs/architecture.html`](docs/architecture.html) for the full diagram.

```
phone ──(Tailscale)──► brain :8080   chat UI + AI DJ + channel manager + adapters
                       icecast :8000  /dead77 /jam /fusion /latenight-jazz
                       navidrome :4533  your own library
        brain ──► liquidsoap ──► icecast     (queues, crossfades, metadata)
        brain ──► archive.org / Claude API   (search, MP3s, the DJ's brain)
```

## Quickstart (on the Mac mini)

Requirements: Docker (OrbStack, Colima, or Docker Desktop) and Tailscale on the host.

```bash
git clone git@github.com:jasonmimick/jam-station.git
cd jam-station
cp .env.example .env        # add your ANTHROPIC_API_KEY, change the icecast passwords
docker compose up -d --build
```

Then from any device on your tailnet:

| URL | What it is |
|---|---|
| `http://<macmini>:8080` | Station web app — chat with the DJ, tune channels |
| `http://<macmini>:8000/dead77` | A channel stream (works in any audio app / CarPlay radio app) |
| `http://<macmini>:4533` | Navidrome — your own library |

`<macmini>` is your machine's Tailscale name or IP (`tailscale status` shows it).
**Don't port-forward anything** — the whole point is that only your tailnet can reach it.

## Adding your own music (the fusion channel)

Drop files into `music/fusion/` and `music/jazz/` (any nesting is fine; name files
`Artist - Title.mp3` for nice now-playing metadata). Navidrome picks them up on its
next scan; the `fusion` channel pulls random tracks from `music/fusion/`.

## Creating channels

Ask the DJ ("build me a channel of peak-energy Umphrey's from 2005–2008") or POST one
yourself — then restart liquidsoap so the new mount opens:

```bash
docker compose restart liquidsoap
```

Channel recipes (the `query` field):

- `source: archive` — `collections[]`, `year`, `min_rating`, `free_text`, `sort`
- `source: library` — `folders[]` (subfolders of `music/`)

## How it works

- **brain** (FastAPI) owns the channel definitions (SQLite), talks to archive.org
  (search by `avg_rating` — that's how the DJ finds the tapes people actually love),
  and runs the Claude tool-calling loop (`search_shows`, `play_show`, `create_channel`, …).
- **liquidsoap** polls `GET /api/next?channel=<slug>` for each channel, crossfades,
  pushes encoded MP3 + metadata to Icecast, and reports track changes back to the brain.
- **Prefetch**: the brain downloads the next few Archive tracks into a shared cache
  volume so playback never stutters on a slow pull (and it's kinder to archive.org).
- Queues top up automatically — Archive channels enqueue *whole shows* (sets play in
  order, like real radio), library channels enqueue random batches.

## Phone setup for the car

- **Channels**: add `http://<macmini>:8000/<channel>` to any radio app
  (Broadcasts on iOS is great), or just use the web app. Works over cellular via Tailscale.
- **Your library**: point play:Sub / Amperfy / substreamer (Subsonic clients) at
  Navidrome — they do CarPlay and offline sync for dead zones.
- **Spotify / YouTube**: not routed through the house by design — those channels are
  AI-curated playlists played by the native apps (adapters on the roadmap).

## Development

```bash
cd brain
pip install -r requirements-dev.txt
pytest                       # archive.org calls are mocked; no network needed
uvicorn app.main:app --reload --port 8080
```

## Roadmap

- Spotify + YouTube playlist adapters (AI curates, native apps play)
- phish.in adapter (Phish isn't on the Archive)
- TTS DJ intros between shows ("that was Cornell '77…")
- "On this day" channel, per-friend request voting

## A note on sources

Everything streamed here is either from the Live Music Archive (bands that explicitly
allow taping/trading) or music you own. Keep it on your tailnet, keep it personal.
