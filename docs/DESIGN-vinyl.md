# DESIGN — Vinyl (the Discogs record wall + playable twins)

**Status:** design agreed 2026-07-20 — build order: Phase 1 (the Wall), then Phase 2
(Playable Twins). Later phases recorded, not scheduled.
**Goal:** Jason's large LP collection (~90% cataloged on Discogs) becomes part of the
station — first as a browsable wall, then as a navigation layer over everything the
station can actually play.

## The constraint that defines the feature

Vinyl has no audio to stream. This is a **catalog integration, not a playback source** —
which fits the station: the shelf, Spot, and sections are already half catalog. The only
audio ever played is audio the station already owns (CD shelf, attic vault, Archive
tapes); the personal-use law is untouched.

## Where the data comes from

The **Discogs API** with a free personal access token (secrets on jam-brain, like SMTP):
- `GET /users/<username>/collection/folders/0/releases` — the whole collection, paged
  100/release, with artist, title, year, formats, cover image URLs, and Discogs'
  **genre + style** taxonomy (styles are the prize: "Hard Bop", "Modal", "Free Jazz" —
  far finer than the MusicBrainz buckets the CD shelf uses).
- Rate limit 60 req/min authenticated — a 2,000-LP collection syncs in ~20 requests.
- Image URLs require auth and are rate-limited → **mirror thumbnails locally**, exactly
  the covers.py pattern: cache beside the data, fetch once.

## Architecture (consistent with everything else)

- **`brain/app/discogs.py`** — sync module. Nightly (and owner-kickable) pull of the
  collection into the music volume:
  ```
  /music/_vinyl/collection.json       the cached catalog (one file, greppable)
  /music/_vinyl/covers/<release>.jpg  mirrored thumbnails
  ```
  Sidecar-files-not-DB, same philosophy as `_album.json`. The sync is additive and
  idempotent; a failed sync leaves the previous cache untouched (offline ≠ empty wall).
- **No AI in the frontend.** The apps see plain endpoints; all intelligence
  (sync, matching) lives in the brain.
- **Secrets:** `DISCOGS_USER` + `DISCOGS_TOKEN` on jam-brain via slab.

### API (members-only, like the shelf)

- `GET /api/vinyl` → `[{id, artist, title, year, styles: [..], genres: [..],
  cover_url, twin: {...}|null}]` (twin appears in Phase 2; null until then)
- `GET /api/vinyl/sections` → `[{name, count}]` — aggregated from styles (coarse
  genre fallback when a release has no styles)
- `POST /api/vinyl/sync` → owner kick; returns counts (synced/new/gone)

## Phase 1 — The Record Wall

The vinyl shelf beside the CD shelf, everywhere:

- **Web**: a Vinyl tab/section in the desktop gallery (the other agent's call on
  placement); same grid/list, sections chips from `/api/vinyl/sections`.
- **Session (Mac/iPad/iPhone)**: "The Records" joins the sidebar / Shelf area —
  the existing gallery UX verbatim (grid/list toggle, section chips, search).
  Cards show the Discogs cover, artist, title, year. **No play button yet** —
  Phase 1 is honest about being a wall.
- Sections come from **styles**, with a count threshold like the shelf's (a style
  with 1 record isn't a section; it folds up into its genre).
- Sort: artist A–Z default (a record crate), toggle to year.

Done means: the collection browsable on all four surfaces, synced nightly, covers
cached, sections navigable.

## Phase 2 — Playable Twins

Each LP resolves to what the station can actually play:

- **`▶ HEAR IT`** — the same album exists digitally (CD shelf now; attic vault when
  its stations land). Tap plays it through the existing on-demand machinery.
- **`((( HEAR THEM LIVE`** — no album twin, but the artist has Archive tapes
  (the archive adapter's search, cached per artist). Tap tunes/plays a show.
- **`VINYL ONLY`** — the honest state, and implicitly the digitization wishlist.

Matching rules (cd-name discipline — never a wrong match):
- Exact-first: normalized artist + album equality against the CD shelf / vault
  catalog (case/punctuation-folded, "The " stripped, & = and).
- Fuzzy only with corroboration: near-identical album title AND same artist AND
  (year within ±1 OR track count matches). Below that: no twin, no guess.
- Twins recompute at sync time and when the shelf changes (rip lands, vault
  station syncs) — an LP **lighting up** as new audio arrives is the product
  moment; surface it ("3 records on your wall just became playable").

## Later phases (recorded, unscheduled)

3. **On the Turntable** — mark an LP as physically spinning; flows into presence +
   history ("Jason is spinning Aja"). No audio, pure family texture.
4. **Spot × collection** — Spot answers "you already own this on vinyl."
5. **Genre backflow** — CD-shelf albums matching a Discogs release adopt its styles.
6. **Pull a record** — random-LP suggester, twin queued as the digital chaser.
7. **Needle-drop pipeline** — digitizing vinyl lands files in the contributor
   inbox → stations; twins then point at your own pressings.

## Open questions (for Jason)

1. **Discogs username** — and is the collection public, or shall we mint a token
   right away regardless (token also lifts image rate limits)?
2. The remaining ~10% not on Discogs: ignore for now, or a manual add path later?
3. Wall placement on the web is the web agent's call — coordinate so "The Records"
   naming matches across clients.
