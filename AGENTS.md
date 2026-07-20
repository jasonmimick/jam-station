# AGENTS.md — guide for AI coding agents working on jam-station

This is the canonical agent guide. `CLAUDE.md` and `.github/copilot-instructions.md`
point here. Keep all three in sync by editing only this file.

## What this project is

A personal, multi-channel internet radio station for one person, family, and a few
approved friends. It runs as a slab system on a home Mac mini and is public at
**https://jam-station.runslab.run** (named Cloudflare tunnel). An AI DJ (Claude
tool-calling) finds and queues live shows from the Internet Archive's Live Music
Archive; a growing CD collection ("LISTEN AND RIP") is ripped on the host and served
to members. Personal use only — never add features that download from, or rebroadcast,
DRM'd/subscription sources (Spotify, Apple Music, YouTube audio). Those services are
integrated *playlist-only*: the AI curates via their official APIs, their native apps play.

## Architecture in one paragraph

`brain` (FastAPI, `brain/app/`) is the only custom service. It owns channel definitions
and members/sessions (**Postgres** via slab-postgres — SQLite is gone, see `db.py`'s
docstring), searches archive.org (community `avg_rating` is the quality signal), runs
the Claude tool loop (`dj.py`), does its own auth (magic link + code + passphrase —
no Clerk/OAuth, deliberately), and serves two no-build UIs: `static/index.html`
(desktop) and `static/mobile.html` (served by user-agent). `liquidsoap`
(`liquidsoap/radio.liq`) polls `GET /api/next?channel=<slug>` per channel, crossfades,
and feeds `icecast` (one mount per channel); it self-reloads when the channel list
changes. CD ripping runs **on the host** (`tools/`), not in a container — slab forbids
host mounts, so the ripper hands finished MP3s to the brain's music volume via
`docker cp`. Wiring: `system.toml` (slab). `docker-compose.yml` still exists for the
full local stack (incl. navidrome, which slab doesn't run yet).

## Layout

```
brain/app/main.py            FastAPI routes (thin — logic lives elsewhere)
brain/app/channels.py        channel manager: seeds, queue top-up, next_track, prefetch
brain/app/dj.py              AI DJ: system prompt, TOOLS schema, tool loop
brain/app/auth.py, mail.py   invite/approve, magic link + 8-char code, sessions; SMTP or console
brain/app/covers.py          album enrichment: MusicBrainz year/tracklist, Cover Art Archive/iTunes art
brain/app/spot.py            photograph music in the wild, vision API identifies it
brain/app/adapters/          one module per audio source (archive.py, library.py, phishin.py, cc.py)
brain/app/db.py              Postgres via a ?->%s facade — no ORM, keep it that way
brain/app/static/index.html  the whole desktop UI (single file, vanilla JS, no build step)
brain/app/static/mobile.html the mobile-web FUNNEL (see Clients), served by user-agent
brain/tests/                 pytest; conftest mocks archive.org AND isolates the DB (see below)
session/                     "Session" — native SwiftUI clients (SessionCore + macOS app + ios/)
session/Makefile             make run (mac) · make ios-sim · make ios-phone · make ios-ipad
liquidsoap/radio.liq         radio engine config (liquidsoap 2.2.x)
tools/                       host-side CD pipeline: rip-cd.sh, cd-watch.sh, cd-tick.sh, cd-name.py
tools/mini/, tools/euler/    launchd plists + helpers (watcher, backups, jam-cdd FDA helper)
system.toml, slab/           the slab system (jam-brain, jam-icecast, jam-radio)
docs/                        architecture.html + DESIGN-*.md (auth built; family/network on hold)
```

## Commands

```bash
cd brain
pip install -r requirements-dev.txt
pytest        # must pass before any commit. Needs a reachable Postgres (slab's is fine):
              # tests create and use <dbname>_test, drop its schema fresh per test, and
              # NEVER touch the configured database — on the mini that is production.
uvicorn app.main:app --reload --port 8080

liquidsoap --check liquidsoap/radio.liq   # after touching radio.liq (apt 2.2.4 close enough)
```

### Deploy

```bash
git push origin main
ssh jason@jasons-mac-mini 'cd ~/business/jam-station && git pull --ff-only'
slab -N jasons-mac-mini deploy jam-brain
```

**`slab deploy` builds from the MINI's checkout (`~/business/jam-station`), not your
local directory** — pull on the mini first or you ship the previous commit. From euler
use `ssh -i ~/.ssh/id_euler`. Verify after: `curl -s https://jam-station.runslab.run/health`.

## Conventions

- **Keep dependencies minimal.** Runtime deps are fastapi, uvicorn, httpx, anthropic,
  psycopg. No ORM, no task queue, no frontend framework. The web UIs are single static
  files with vanilla JS — they must work from a browser with no build step.
- **The path IS the tags.** The catalog reads artist/album/title from folder and file
  names (`Artist - Album/07 Title.mp3`), never from ID3. Fix names, not tags.
- **Adapters are the extension point.** A new audio source = a new module in
  `brain/app/adapters/` exposing track dicts (`url`, `title`, `artist`, `album`),
  plus a `source` value handled in `channels.ensure_queue()`.
- **New DJ abilities** = a tool schema in `TOOLS` (`dj.py`), a branch in `_run_tool()`,
  results JSON-serializable and truncated (see existing 20k cap).
- **Tests mock the network** (`httpx.MockTransport` in `tests/conftest.py`) and run in
  the dedicated `_test` database with `MIN_QUEUE=1` (next_track's background top-up
  thread races assertions otherwise). Every new endpoint/adapter needs a test.
- **`/api/next` returns `annotate:` URIs.** Titles/quotes are escaped in
  `channels._annotate()`; keep double quotes out of values.
- **UI state lives in localStorage** (accent, dance, screensaver pick, pane collapse,
  column widths, favourites) — no server round-trips for taste.

## Auth, in one breath

Email is the identity; there is no identity provider (deliberately no Clerk/OAuth).
Three ways in, all in `auth.py`: a reusable **magic link** (`/k/<token>`), a
**passcode** (8 chars generated, or 6–24 owner-chosen — normalized UPPERCASE, no
spaces/dashes, at creation and at sign-in, so both must use `normalize_code`), and an
optional self-set **passphrase** (PBKDF2). The owner adding you IS the approval:
`/api/owner/add` creates the member and **emails them the link + passcode**
(`send_key_email`; "New link"/rotate re-sends a fresh pair and kills the old).
Keys are stored hashed and shown once. Sessions are 30-day HttpOnly cookies.
`mail.py` speaks SMTP; the `console` backend prints the mail so the whole flow works
with zero credentials — the mini has real SMTP secrets set on `jam-brain`.

## Clients & the shelf's sections

Five front-ends, one brain: the desktop web (`index.html`), the native **Session** apps
(`session/` — macOS, iPhone, iPad; SwiftUI; no App Store presence yet, no developer
account), the mobile web (`mobile.html`), **dad mode** (`dad.html` at `/dad`), and radio
apps hitting icecast directly.
**Mobile web is a FUNNEL, not an app**: station list + radio playback + sign-in (invite
links land there) + a "Session for iPhone — coming soon" teaser on Apple devices. Don't
grow it; grow the apps and the desktop.
**Dad mode (`/dad`)** is a dead-simple radio: big station-photo tiles, one play button — the
generic simple view. **Personal radio (`/<handle>`)** is the per-member evolution: the handle
is the email local part kept verbatim (`jmimick+dad@gmail.com` → `/jmimick+dad`, header
"jmimick+dad Radio"), computed by `auth.handle_for` (not stored), resolved by
`auth.member_by_handle`. The `/{handle}` route is registered LAST in main.py so real routes
win and an unknown handle 404s — don't add routes after it. Shows the whole dial today; their
contributed slice up top is a TODO (needs upload attribution).

**Family-facing pages** (all public, self-hosted on the station): `/guide` (Tailscale
contributor how-to, Session look, teases the "become a broadcaster" carriage layer — keep that
promise), `/session` + `/session/download` (the Session Mac app — zip lives in the **music
volume** `/music/_downloads/Session-mac.zip`, NOT git; re-copy on a new build via `docker cp`).
The **welcome email** (`auth.send_key_email`) links all of it: sign-in, `/<handle>`, `/session`,
`/guide`. The desktop account panel (☺) links "Your radio" + the guide for signed-in members.

## Family / affiliate — the two layers (see docs/DESIGN-network.md, DESIGN-family-radio.md)

The family-radio vision splits into two independent, composable layers — don't conflate them:
1. **Sourcing** — how one person turns a big archive into channels on THEIR station. The
   **attic** project (`~/projects/attic`, a wiped Time Capsule vault of ripped/copied music)
   is the content engine; the planned **"attic" source adapter** streams vault music through
   jam-station without copying it onto the full mini (host music server on the mini +
   `host.docker.internal` reach from the brain + a `/attic/<path>` proxy for browser+liquidsoap).
2. **Carriage** — how a family member's whole STATION appears on your dial: a station-to-station
   relay. Their jam-station makes icecast streams behind their own tunnel; yours carries the
   remote stream as a channel (extends the existing `/stream/<slug>` proxy to a remote URL).
   **COMING, not built.** This is the "become a real broadcaster" path teased at the bottom of
   `/guide`: a contributor sends folders (built, below); a broadcaster runs their own sovereign
   station that the network carries. The `/guide` page promises it — keep that promise.
   **Contributor path (Tailscale):** dad is technical and wants to push his music folders TO the
   station. Cloudflare free caps uploads at 100 MB/request, so the answer is **Tailscale** (mini
   is `jasons-mac-mini` / `100.91.29.30` on the tailnet; euler is on it too). Plan: dad joins the
   tailnet, rsyncs folders to a watched **inbox** on the mini, jam-station ingests each folder as
   a named station (same "feed it, it appears" ritual as the CD drive). The folder→station ingest
   is shared with attic's vault-music work.

The shelf has **sections** (genres): auto-mapped by the enricher (release →
release-group → artist fallback), owner-pinned via `POST /api/library/genre`.
`GET /api/library/genres` lists sections; `GET /api/library/mix?genre=` returns a
show-shaped shuffled mix. Sections ≥3 records become **`shelf-*` stations
automatically** (`sync_genre_channels`) — and these are **mix-only**: no icecast
mount, every client "tunes" them by playing the mix through its own on-demand
machinery (web: `tuneMix`/`MIX` prefix; a `/stream/shelf-*` request always fails —
403 for anonymous, 404 for members — and that's correct). `GET /api/dial` gives now-playing for every broadcast channel in one
call — clients poll it instead of hammering `/api/nowplaying` per channel.

## Gotchas

- Queue top-ups are guarded by per-channel `threading.Lock`s (`channels._lock_for`).
  Don't remove the non-blocking acquire or two top-ups will double-queue a show.
- Archive channels enqueue **whole shows** (sets play in order); library channels
  enqueue random batches. Preserve that distinction.
- **CD identification is exact-first** (`tools/cd-name.py`): MusicBrainz disc ID from
  the TOC, then fuzzy raw-TOC — but a fuzzy candidate is only believed after its
  per-track offsets check out within 5s. The fuzzy search matches on rough total
  length alone and once named an *Are You Experienced* disc "Fiddler's Green". Blank
  stdout = dated Unknown folder. NEVER a wrong name. Test with `--toc "1+17+…"`.
- The rip ledger (`~/.jam-ripped` on the mini) is keyed by a disc signature — a disc
  that ripped (even misnamed) will be skipped forever unless its line is removed.
- **Folder mtime IS "date added"** (gallery sorts by it). Repair renames bump it and
  shuffle newest-first order — after any catalog surgery, `touch -d "<rip time>"` the
  folder back to its ledger timestamp.
- Ripping runs on the host because containers can't see the drive; a killed rip leaves
  the disc mounted and unledgered, and the watcher retries it. Partial rips never
  reach the volume (staged in a temp dir, `docker cp` only on success).
- **Web Audio is an opt-in trade on iOS**: routing through it pauses playback on lock.
  EQ open / "Let it dance" are the opt-ins; a restored dance session defers graph
  creation to the first gesture (a gestureless AudioContext starts suspended and MUTES
  the element). Desktop auto-inits on first play.
- The desktop page never stacks its columns — narrow windows shrink the side panes
  (or collapse them to rails). The old <1100px stacked fallback is gone; phones get
  `mobile.html` by user-agent. Don't reintroduce a breakpoint that rearranges `.app`.
- Phish is not on the Archive (band policy) — that's what `adapters/phishin.py` is for.
  Commercial 70s fusion/bebop isn't either; it needs the owner's ripped library.
- **Session (native apps)**: design in `docs/DESIGN-session*.md`; reuses the web's
  design system verbatim. Device installs go through `session/Makefile` targets
  which VERIFY by reading the device's own app listing (a `| tail` pipe once
  masked a failed build and re-installed a stale bundle for a whole day —
  never trust an install without the `App installed` line + build number).
  Free-team signing: builds expire after 7 days; team id lives in
  `session/ios/project.yml`. Engine + image loaders must attach cookies
  explicitly (AVURLAssetHTTPCookiesKey / URLSession.shared) — AVPlayer and
  AsyncImage do NOT send them, and members-only /music 403s silently.
- **Genres**: `_album.json` carries `genres` (+ `genres_owner` pins curation);
  covers.py maps MB tags→buckets falling back release→release-group→artist;
  genre channels (`shelf-*`) are MIX-ONLY — on the dial but never mounted by
  liquidsoap; clients play them as instant on-demand mixes via /api/library/mix.
- liquidsoap is pinned to `savonet/liquidsoap:v2.2.5`. Its scripting language breaks
  between minor versions — if you bump the pin, re-run `--check` and expect churn.
- `liquidsoap --check` also RUNS top-level code; with no brain reachable the script
  intentionally exits 1 via `shutdown()`. Exit 1 with no output ≠ a syntax error.

## Roadmap (safe next tasks — see BACKLOG.md for the full list)

1. The rename (candidate: Shortwave) — repo, slab apps, tunnel, docs, UI, PWA icons
2. launchd for the cloudflared tunnel + slab daemon (a reboot still downs the station)
3. Load-your-own-music volume mount — lights up 70s Fusion / BeBop
4. TTS DJ intros via a liquidsoap `request.queue` jingle source
5. "On this day" channel: archive search with `date:*-MM-DD` free_text
