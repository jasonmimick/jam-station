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
brain/app/adapters/          one module per audio source (archive.py, library.py, phishin.py, cc.py, attic.py)
brain/app/db.py              Postgres via a ?->%s facade — no ORM, keep it that way
brain/app/static/index.html  the whole desktop UI (single file, vanilla JS, no build step)
brain/app/static/mobile.html the mobile-web FUNNEL (see Clients), served by user-agent
brain/tests/                 pytest; conftest mocks archive.org AND isolates the DB (see below)
session/                     "Session" — native SwiftUI clients (SessionCore + macOS app + ios/)
session/Makefile             make run (mac) · make ios-sim · make ios-phone · make ios-ipad
liquidsoap/radio.liq         radio engine config (liquidsoap 2.2.x)
tools/                       host-side CD pipeline: rip-cd.sh, cd-watch.sh, cd-tick.sh, cd-name.py
tools/attic-server.py        the SHELF SERVER: serves vault music (AFP TC) to the brain over HTTP
tools/attic-genres.py        one-shot MusicBrainz artist→genre pass -> _genres.json per vault root
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
  names, never from ID3. Fix names, not tags. Three filename forms (`adapters/library._meta`):
  `Artist - Title.mp3` (loose), `Artist - Album/07 Title.mp3` (a normal ripped CD — artist from the
  folder), and **`Various Artists - iSS.1/03 Pink Floyd - Speak to Me.mp3`** (a mix — the track
  number is stripped FIRST so a per-track artist survives). For a Various-Artists comp: folder
  `Various Artists - <Album>`, files `NN <Artist> - <Title>.ext`, and a `_album.json` with an
  explicit `"artist"` (e.g. `"Various Artists"`) — that overrides the first-track artist on the
  shelf card. (`iSS.1` — "Isabella + Sofia Songs #1", a homemade disc — is the worked example.)
- **Album art = files in the album folder, no DB.** `_cover.jpg` is the single primary front cover
  (grid/now-playing/lock-screen). Additional typed images are `_art-<slug>.jpg`
  (`tracklist`/`back`/`disc`/…). `library.album_images(dir)` returns `[{type,url}]` (front first);
  `api_library_album` includes `images`; upload is `POST /api/library/cover` with a `type` form
  field (`front`→`_cover.jpg`, else `_art-<slug>.jpg`). Enricher only ever manages `_cover.jpg`.
  Mark a homemade comp's `_album.json` `{"tried":true,"itunes":true,"genres":[]}` so covers.py
  leaves it alone.
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
- **Site banner + machine /health.** Owner sets a banner (account panel ☺ → Site banner;
  `POST /api/owner/banner`, stored in the `settings` table) — deploy heads-ups/news, shown
  atop desktop + mobile via public `GET /api/banner`, dismissible per MESSAGE (a new text
  re-shows). `GET /health` is machine-readable for agents/monitors: `ok` keeps its original
  meaning (brain+db up — every old verify still works); `db`/`icecast`/`shelf`/`channels`/
  `banner` say which piece is down. Check /health before diagnosing "the station is broken".

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

**Sibling project heads-up (2026-07-21):** **shoebox** — a family PHOTO-sharing app over the
attic vault — is designed, LGTM'd, and named (its own project: `~/projects/shoebox`, spec
`DESIGN.md`, mocks `docs/mocks/`). It copies jam-station's patterns
(host-daemon contract, magic-link/passcode auth, slab deploy) but is a SEPARATE app with its
own DB and member list — don't add photo features to jam-station, and don't touch **port 8519**
(reserved for its photo server; 8517 stays the music shelf server).

The family-radio vision splits into two independent, composable layers — don't conflate them:
1. **Sourcing** — how one person turns a big archive into channels on THEIR station. The
   **attic** project (`~/projects/attic`, a wiped Time Capsule vault of ripped/copied music)
   is the content engine; the **"attic" source adapter** streams vault music through
   jam-station without copying it onto the full mini. **BUILT 2026-07-20** (spec:
   `docs/DESIGN-vault-stations.md`): the vault is AFP-mounted on the **host** at
   `/tmp/tc-afp/attic-vault/` (~65 GB, artist-organized), the container can't see it, so
   `tools/attic-server.py` (stdlib, launchd `run.attic.server.plist`, port 8517) serves the
   **shelf-server contract** — `/catalog.json` (with `categories` + per-track `genres` from a
   per-root `_genres.json`, filled by `tools/attic-genres.py`) + ranged `/file/<root>/<path>` +
   `/health` — and `adapters/attic.py` consumes it via `ATTIC_SERVER_URL`
   (`http://host.docker.internal:8517`). **The contract is the extension point**: any machine
   that speaks it can feed stations (dad's Mac over the tailnet, later). Stations: **The Vault**
   (`vault`, `{"all": true}`, mounted), **Artist Spotlight** (`spotlight`, `{"spotlight": true}`,
   one random artist per top-up, mounted), and auto-synced **`vault-<genre>` category channels**
   (`sync_attic_channels`, mix-only like `shelf-*`, from the server's declared categories).
2. **Carriage** — how a family member's whole STATION appears on your dial: a station-to-station
   relay. Their jam-station makes icecast streams behind their own tunnel; yours carries the
   remote stream as a channel (extends the existing `/stream/<slug>` proxy to a remote URL).
   **COMING, not built.** This is the "become a real broadcaster" path teased at the bottom of
   `/guide`: a contributor sends folders (built, below); a broadcaster runs their own sovereign
   station that the network carries. The `/guide` page promises it — keep that promise.
   **Contributor path: two generations, one currently live, one built-and-tested-but-
   not-wired-up-yet.**

   **Generation 1 (SSH + rsync — LIVE today, Dad's currently-installed Session and his
   `jam-outbox.command` both still use this, nothing has changed for him):** a dedicated
   macOS user `mark` on the mini (non-admin, SSH pubkey-only — `Match User mark` block
   in `sshd_config`, `PasswordAuthentication no`) owns `/Users/mark/jam-inbox` outright.
   `tools/jam-inbox.sh` (launchd `run.jam.inbox`, polls every 20s) imports each new,
   settled top-level folder as its own `source=library` station — `docker cp`s the audio
   into the brain's `/music/inbox/` volume, creates the channel, ledgers it so it imports
   exactly once. Both clients ship with their own dedicated, pre-authorized SSH key baked
   in (`session/Resources/dad_key`, gitignored) so the contributor never runs
   `ssh-keygen` themselves.
   **The problem with generation 1, found live 2026-07-22:** that key is baked into
   every download of Session, and `/session/download` is a PUBLIC URL — anyone who finds
   it gets the same key, with write access to the inbox. Bounded blast radius (that
   account can only write one folder, no shell), but a real hole, and every upload was
   attributed to the same generic account regardless of who actually sent it.

   **Generation 2 (personal API keys — BACKEND BUILT + TESTED 2026-07-22, clients NOT
   yet rewired to use it):** the SaaS-API-key shape, not a shared secret in a
   downloadable app. A member signs in with jam-station's existing magic-link/passcode
   auth (nothing new there) and `POST /api/contribute/token` mints them a personal
   upload key (`contribution_tokens` table, `auth.create_contribution_token` — one
   active token per member, minting a new one revokes the old). `POST /api/contribute`
   (`Authorization: Bearer <token>`, multipart `folder` + zip `file`) validates the
   token, unzips straight into `/music/inbox/<folder>/`, and calls
   `channels.create_channel` **in-process** — no host daemon, no polling, no
   `jam-inbox.sh` involved for this path at all. Every upload is recorded in
   `contributions` (email, slug, folder_name) for the personal-radio "contributed
   slice" (`auth.handle_for`/`member_by_handle`'s TODO, finally addressed). Verified
   end-to-end for real over the public HTTPS endpoint: signed in, minted a token,
   uploaded a real zip, station appeared, contribution recorded, old token correctly
   rejected after minting a new one.
   **What's left**: rewire Session's Send Music panel and `tools/jam-outbox.command` to
   POST to `/api/contribute` with a stored personal token instead of `rsync -e ssh`
   with the shared key — once that ships, generation 1 (the `mark` account, its SSH
   key, the sshd_config block, `Resources/dad_key`) gets retired for good. Until then
   BOTH generations are live and harmless side by side; nothing contributors currently
   use is broken by generation 2 existing.
   **An earlier same-night idea (Tailscale identity via `tailscale whois`, a host
   daemon `jam-contribd`) was built, hit an unresolved Python-3.9 socket-bind bug under
   launchd, and was abandoned in favor of the simpler API-key shape above** — its
   design doc (`docs/DESIGN-contributor-identity.md`) and code
   (`tools/mini/jam-contribd.py`, `run.jam.contrib*.plist`) are left in the repo as a
   record, not a live path; the daemon is stopped (`launchctl unload`), don't restart it.

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

- **A contributor's SSH key can check out cryptographically and still get killed** —
  `ssh -v` shows "Server accepts key" then the connection just closes, no error. Cause:
  macOS's **Remote Login access list** (System Settings → Sharing → Remote Login) gates
  actual sessions via the `com.apple.access_ssh` group, which by default nests only `admin` —
  a deliberately non-admin contributor account (like `mark`) passes auth then gets dropped
  post-auth. Fix, without making them an admin: `sudo dscl . -append
  /Groups/com.apple.access_ssh GroupMembership <user>`.
- **`sysadminctl -addUser ... -home /path` does NOT create the home directory** — it only
  assigns the path ("Home directory is assigned (not created!)" in its own output). Follow
  with `sudo createhomedir -c -u <user>` or every first write into that account's home fails
  with a plain "Permission denied" that looks like an ownership bug but isn't one.
- **`rsync`'s `-e` option does its own naive whitespace-splitting — no shell-style quoting.**
  A staged helper path under `~/Library/Application Support/...` (has a space in "Application
  Support") gets chopped mid-string and the second half gets fed to `ssh` as a bogus hostname
  ("Could not resolve hostname support/session/dad_key" — hit this live building Session's
  Send Music panel). Never stage anything referenced inside an `-e` value under a
  space-containing path; the destination/source rsync arguments themselves are fine (real
  argv, not shell-split), only the `-e` command string is the trap.
- **macOS's bundled `rsync` is openrsync (BSD), not GNU rsync 3.x** — `--chmod=D755,F644`
  (the common numeric form) is rejected outright ("invalid argument"); it only accepts the
  symbolic relative form (`--chmod=Fa+r,Da+rx`). Worse: even the symbolic form, and
  `--no-perms`, did NOT reliably override a source file's existing permissions in testing
  (a contributor's real files landed owner-only-readable regardless of either flag) — a
  real contributor's files can carry arbitrary restrictive permissions from wherever they
  originally got them, and jam-inbox.sh (running as a different account) can't read them.
  **The fix that actually works**: `chmod -R go+rX <folder>` on the SOURCE side, before
  rsync ever runs — the contributor always owns their own files, so relaxing permissions
  there always succeeds no matter how restrictive they started. Both `tools/jam-outbox.command`
  and Session's Send Music do this now; don't reach for rsync flags to solve this again.
- **`db.py`'s schema init does a naive `SCHEMA.split(";")`** — it has no idea what's a
  comment and what's SQL. A semicolon anywhere in a `--` comment's PROSE (ordinary English
  punctuation, not code) breaks the split and corrupts the NEXT statement with a syntax
  error at whatever word follows — hit this twice writing the contributions/
  contribution_tokens tables tonight. Never use a semicolon inside a schema comment; rephrase
  instead (an em dash or period always works).
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
  **Attic's `_genres.json` tags work the same way for a manual, non-MusicBrainz label**:
  hand-write `{"Artist Name": ["Any Tag You Want"]}` at a root's top level and it becomes a
  real category (`sync_attic_channels` turns it into a `vault-<tag>` station once ≥3 records
  share it) — no code needed. Worked example: a disc of Dad's old MP3s landed at its own root
  (`cdmusic1` in `ATTIC_ROOTS`) with every one of its 13 artists tagged `"Dad's old mp3 cd"`,
  and it showed up as a real station on the next catalog walk.
- **Attic/vault**: track urls are stored SAME-ORIGIN (`/attic/<root>/<path>`) like `/music/` —
  the browser plays them through the brain's members-gated proxy (the browser can NOT reach
  `host.docker.internal`), and `_for_liquidsoap` makes them absolute+keyed for the radio
  container. `PRIVATE_SOURCES = {"library", "attic"}` drives both channel privacy and the
  `/stream` gate. Mix-only channels (any `query.genre`, shelf-* AND vault-*) are served by
  `GET /api/mix?slug=` which dispatches by source (`/api/library/mix` stays for Session
  back-compat). Shelf server down → attic catalog negative-cached 60s, vault mounts drop from
  channels.liq (= a jam-radio restart) and stations read OFF AIR — that's degradation, not a
  bug. NEVER expose port 8517 through the tunnel; the `vault-` slug prefix belongs to
  `sync_attic_channels` (it retires strays — The Vault is `vault`, Spotlight is `spotlight`).
  **Catalog serving is stale-first, and that's load-bearing** (outage 2026-07-20): the server
  once re-walked the AFP share INLINE on TTL expiry (~40s); the brain's 15s timeout blanked
  the vault on every dial and piled up concurrent walks until the server hung. Now: catalog
  requests answer instantly from cache (stale ok), re-walks are single-flight in a background
  thread (only cold boot waits), handler keep-alive times out at 75s, log lines carry
  timestamps. Brain side: a failed fetch serves the LAST-KNOWN catalog (never blank a working
  dial); an empty cache retries in 5s. Don't "simplify" any of that back to inline/fresh-only.
  **Dedup is catalog-layer, disk keeps every copy**: `_dedup()` in attic-server hides
  non-canonical duplicate album folders (most tracks → m4a>mp3>wma → first root; `_dedup.json`
  sidecar `force`/`keep_all` overrides; report at `/dupes.json`). WMA transcodes are cached as
  real files (`~/.attic-transcode`, LRU 2GB) and served sized+seekable — streaming ffmpeg
  stdout silently broke old browsers (Fire/Silk).
  The vault is ~7,400 **WMA** rips: browsers can't play WMA, so attic-server transcodes
  wma→mp3 live via **`/opt/homebrew/bin/ffmpeg`** (the `/usr/local/bin` one is a BROKEN
  Intel-brew leftover — the server probes `-version` before trusting any candidate; a broken
  ffmpeg = wma served raw). Transcoded streams have NO Content-Length/Range — not seekable.
  launchd is silently DENIED the AFP mount without Full Disk Access — `~/bin/jam-atticd`
  (the jam-cdd pattern, built by install.sh) is the FDA-holding wrapper;
  `run.attic.server.plist` runs it. iTunes-library nesting (`iTunes/iTunes Media/Music/...`)
  is stripped before Artist/Album derivation.
- **Attic UI surface** (web desktop; Session parity spec'd in `docs/DESIGN-session-attic.md`):
  "The Attic" gallery tab browses the crate (`GET /api/attic/albums`, ~1,340 albums; grid
  shows generated placards ON PURPOSE — art is fetched LAZILY per album via
  `GET /api/attic/cover?artist&album` → iTunes, cached, misses negative-cached 7 days; never
  bulk-prefetch it). Attic albums play through the SAME door as CDs
  (`/api/library/album?dir=attic:<root>/<folder>`). `GET /api/attic/artist?name=` is the
  everything-by-them shuffle. The now-playing byline grows "▸ record / ▸ artist" chips on any
  `/attic/` track. Gallery clicks DON'T jump to Now Playing — browsing stays put, the tab
  bar's ▶ line is the way over. Whole RECORDS can be liked (♥ on album cards, CDs + Attic;
  localStorage `jam-fav-albums`, "Liked first" sort) — separate list from track favourites;
  both are localStorage until the favourites-sync backlog item lands. The gallery filter box
  filters as you type (it once only worked by accident via the 30s poll).
- liquidsoap is pinned to `savonet/liquidsoap:v2.2.5`. Its scripting language breaks
  between minor versions — if you bump the pin, re-run `--check` and expect churn.
- `liquidsoap --check` also RUNS top-level code; with no brain reachable the script
  intentionally exits 1 via `shutdown()`. Exit 1 with no output ≠ a syntax error.
- **`/api/channels.liq` MUST be deterministic** (byte-identical when the channel set is
  unchanged). `radio.liq` restarts the whole radio container whenever that text differs from its
  boot snapshot, dropping every live stream mid-song. A nondeterministic `ORDER BY created_at`
  (ties on bulk-seeded rows) caused a 290-restart phantom loop (fixed 2026-07-20): the endpoint now
  `sorted()`s its lines and `list_channels` orders `created_at, slug`. Never emit anything volatile
  (timestamps, RANDOM order, now-playing) into that endpoint. The radio container is
  **`slab-jam-radio`** (liquidsoap), separate from `slab-jam-brain` (FastAPI) and `slab-jam-icecast`.
- **Mini ops (from euler).** `ssh -o IdentitiesOnly=yes -i ~/.ssh/id_euler jason@jasons-mac-mini`
  (bare ssh has no key). Docker binary is **`/usr/local/bin/docker`** (not on the non-login PATH);
  containers `slab-jam-brain` / `slab-jam-radio` / `slab-jam-icecast`. To run brain code/one-offs
  (invites, tagging, catalog checks) avoid ssh→docker→sh→python quoting hell — **base64 the python**:
  `B64=$(printf '%s' "$PY" | base64); ssh … "/usr/local/bin/docker exec slab-jam-brain sh -c 'cd /app && echo $B64 | base64 -d | python'"` (pipe through `grep -v -i warning`). Send an invite this
  way: `auth.create_key_member(name, email=…)` then `auth.send_key_email(name, email, link, code,
  cc=…)` (`cc` is optional, copies the owner). The mini's docker `/music` is a **volume**, not the
  host FS — `docker cp` (or a `/music/_incoming` staging dir) to get host files in.

## Roadmap (safe next tasks — see BACKLOG.md for the full list)

1. The rename (candidate: Shortwave) — repo, slab apps, tunnel, docs, UI, PWA icons
2. launchd for the cloudflared tunnel + slab daemon (a reboot still downs the station)
3. Load-your-own-music volume mount — lights up 70s Fusion / BeBop
4. TTS DJ intros via a liquidsoap `request.queue` jingle source
5. "On this day" channel: archive search with `date:*-MM-DD` free_text
