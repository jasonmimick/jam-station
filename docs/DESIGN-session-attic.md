# Session ↔ The Attic — handoff for the Session (macOS/iOS) agent

**Audience:** the agent building the native Session apps (`session/`).
**Ask:** bring "The Attic" — the vault music feature shipped on the web 2026-07-20 — to the
Mac and iOS apps. The web desktop (`brain/app/static/index.html`) is the reference
implementation; Session reuses the web's design system verbatim, so match its UX.
**Background:** `docs/DESIGN-vault-stations.md` (architecture), AGENTS.md §Family/affiliate
(context). Short version: ~16,000 tracks / ~1,340 albums rescued from old drives live on a
Time Capsule; a host-side "shelf server" streams them through the brain. Everything below is
brain API — Session never talks to the shelf server directly.

## What the attic is, product-wise

A second record crate next to the CD shelf: the family's rescued music collection,
browsable and playable, plus radio stations built from it. Everything is **members-only** —
same session cookie as the rest of Session.

## The five surfaces to add

1. **Vault stations on the dial** (probably free): `/api/channels` now includes, for members:
   - `vault` (The Vault — all 16k tracks, shuffle) and `spotlight` (Artist Spotlight — one
     random artist per batch). These are REAL broadcast channels: icecast mounts, tune via
     `/stream/<slug>` exactly like every other station. If Session already renders the
     member dial, these appeared automatically.
   - `vault-<genre>` × ~12 (The Vault — Rock, Jazz, …): **MIX-ONLY**, like `shelf-*`. No
     icecast mount exists — `/stream/vault-rock` will always fail. Recognize them the same
     way as shelf sections: `query.genre` is set. Tune = play an on-demand mix (see 2).

2. **The generic mix endpoint** — `GET /api/mix?slug=<channel>&count=40`
   Works for EVERY mix-only channel (shelf-* AND vault-*), dispatching by source
   server-side. Response is show-shaped (same as `/api/library/mix`): `{channel, album,
   artist, tracks:[{url,title,artist,album,cover_url?}], playing:-1}`. Endless-mix pattern:
   when the queue nears its end, fetch again and append (web does this 2 tracks from the
   end). Session currently uses `/api/library/mix?genre=` for shelf sections — that still
   works, but **`/api/mix?slug=` is the forward path; adopt it for both** and shelf/vault
   need no special-casing.

3. **The Attic crate (browse)** — `GET /api/attic/albums`
   `[{dir, artist, album, tracks, src:"attic"}]`, ~1,340 entries, sorted artist→album.
   `dir` looks like `"attic:drive03/Nirvana/Bleach"` — it's an opaque key. Render like the
   CD gallery (generated placard tiles; see art note below). Duplicates are real (the vault
   keeps every copy it rescued) — render them as-is.
   **Play an album:** `GET /api/library/album?dir=<the attic: dir>` — yes, the same door as
   CD albums; it dispatches on the `attic:` prefix. Ordered tracklist, show-shaped.

4. **Jump from a playing track to its record / artist** (the web's "▸ record / ▸ artist"
   byline chips). Any attic track's `url` is `/attic/<root>/<folder>/<file>`:
   - **record**: `"attic:" + <root>/<folder>` (drop the filename, percent-DECODE first) →
     `/api/library/album?dir=…`
   - **artist**: `GET /api/attic/artist?name=<artist>&count=60` → shuffled everything-by-them,
     show-shaped; re-fetch + append when it runs dry (it reshuffles server-side).
   Offer these on the now-playing screen whenever the current track's url starts `/attic/`.

5. **Album art, lazily** — attic tracks carry `cover_url` (`/api/attic/cover?artist=…&album=…`).
   First request fetches from iTunes (≤1 s), then it's cached; 404 = no art, show the placard.
   **Do NOT prefetch art for the whole crate list** — 1,300+ cold lookups would hit iTunes
   rate limits (the albums list deliberately omits `cover_url`). Fetch when an album is
   opened or a track plays. Misses are negative-cached server-side for 7 days.

## Gotchas that will bite the apps

- **Cookies, again**: `/attic/*`, `/api/attic/*`, `/api/mix` are all members-gated. AVPlayer
  and AsyncImage do NOT send cookies — attach them explicitly (AVURLAssetHTTPCookiesKey /
  URLSession.shared), exactly like `/music` (AGENTS.md §Session gotcha). A missing cookie is
  a silent 403 and an empty crate.
- **WMA tracks are non-seekable streams.** ~7,400 vault tracks are WMA; the server transcodes
  them to MP3 on the fly, so the response has **no Content-Length and no Range support** —
  duration is unknown until the end and scrubbing won't work. AVPlayer handles
  connection-close MP3 streams fine; just don't rely on duration/seek for these. (M4A/MP3
  vault tracks are served raw with Range — they seek normally.)
- **The shelf server can be down** (TC unmounted): vault channels drop from `/api/channels`
  (unplayable) or return empty mixes. Treat as OFF AIR, not an error state.
- **`playing:-1`** in show-shaped responses means "nothing started yet" — same contract as
  every other show payload.

## Definition of done

- Vault broadcast stations tune like any station; `vault-*` genre stations play as endless
  mixes via `/api/mix?slug=`.
- An "Attic" section in the app's browse UI: album grid → album → plays in order.
- Now-playing on an attic track offers "play this record" and "play this artist".
- Art appears lazily; no bulk art prefetch.
- Works signed-in on Mac + iPhone + iPad; verify installs per `session/Makefile` rules
  (trust only the `App installed` line + build number).

## Optional parity

The web also has **record-level likes**: a ♥ on album cards (localStorage
`jam-fav-albums`, "Liked first" gallery sort). It's client-local for now — if Session adds
it, keep its store client-local too; a server favourites sync is a separate backlog item
that will cover tracks AND albums when it lands.
