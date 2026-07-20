# AGENTS.md — Session (native SwiftUI clients)

Session is the native front-end family for jam-station: **macOS + iPhone + iPad**, one
SwiftUI codebase (`SessionCore` + platform targets). The brain is the same FastAPI service
every client talks to — **the root `../AGENTS.md` is canonical** for the backend, the API,
auth, and the sourcing/carriage design. This file is the app-specific layer.

## Build / run

`session/Makefile` targets: `make run` (mac), `make ios-sim`, `make ios-phone`, `make ios-ipad`.
Device installs VERIFY by reading the device's own app listing — never trust an install without
the `App installed` line + build number (a `| tail` once masked a failed build and re-installed a
stale bundle for a day). Free-team signing: builds expire after 7 days; team id in
`session/ios/project.yml`. Design in `../docs/DESIGN-session*.md`; reuses the web design system.

## The one gotcha that bites every time

**AVPlayer and AsyncImage do NOT send cookies.** Members-only `/music` and `/stream` return 403
silently if you don't attach them explicitly (`AVURLAssetHTTPCookiesKey` for the engine,
`URLSession.shared` cookie handling for images). Any new media/image fetch must carry the session
cookie or it 403s with no error.

## What the apps consume (all via the brain's API)

- `GET /api/channels` — the dial (with `art_url`, `playable`, `private`). Genre `shelf-*` stations
  are **mix-only** (no icecast mount) — play them as on-demand mixes via `/api/library/mix`, never
  `/stream/shelf-*` (that 403/404s, correctly).
- `GET /api/dial` — now-playing for every broadcast channel in one call (poll it, don't hammer
  `/api/nowplaying`).
- `/stream/<slug>` for radio; `/music/<path>` for on-demand library/CD tracks (cookie!).
- Sections/genres: `/api/library/genres`, `/api/library/mix`, `POST /api/library/genre`.

## New context this session (2026-07-20) — coming to the dial

- **Dad mode** is a WEB front-end (`/dad`) — dead-simple radio, the receiving face of the
  family/affiliate story. Not a Session target, but the same "big tiles + one play button" ethos
  is a good reference if a simplified/"family" Session mode is ever wanted.
- **attic vault music** (the `~/projects/attic` archive of ripped/copied drives) is becoming a
  jam-station **source** — it will surface as ordinary channels in `/api/channels`, so **the apps
  get it for free** once the backend adapter ships. No app change needed to play vault stations.
- **Affiliate/carriage** (a family member's whole station carried on your dial) is a future
  backend channel type; again it appears as a normal channel to the apps. See root AGENTS.md
  "Family / affiliate — the two layers."

The through-line: new sources (attic, affiliate carriage) all land as **regular channels** in the
existing API, so the apps rarely need to know where a channel's audio comes from — play the dial.
