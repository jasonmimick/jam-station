# Handoff — record likes should follow the member (web agent ↔ Session agent)

**From:** the Session (native apps) agent · **To:** the web/brain agent
**Status:** flagged 2026-07-20, agreed with Jason. Not urgent; do it once, together.

## The issue

"Like a whole record" (`b0dc2e2` web, Session build 35) shipped **local-only** on both
clients — web keeps liked dirs in localStorage (`jam-fav-albums`), Session mirrors that in
UserDefaults (`likedAlbums`). Correct per the "UI state lives in localStorage" convention,
but record likes are turning into *taste that should follow the member*, exactly like track
favourites already do: like a record on the Mac at the desk, expect to see it hearted on the
phone in the car. Track favourites solved this (`auth.favourites`, url-keyed, merge on first
sign-in); record likes deserve the same lane.

## Proposed server addition (mirror the track-favourites pattern verbatim)

Keyed by the album **`dir`** — it's already the stable identity everywhere, and the
`attic:` prefix keys vault records with zero extra design:

- `GET  /api/favourites/albums` → `{"albums": ["cds/…", "attic:…", …]}` (member-gated)
- `POST /api/favourites/albums/add`    `{dir}` → `{ok}`
- `POST /api/favourites/albums/remove` `{dir}` → `{ok}`
- `POST /api/favourites/albums/sync`   `{local: [dir, …]}` → `{"albums": [merged]}`
  **MERGE, never overwrite** — same law as track favourites and for the same reason:
  likes exist on two devices before the first sync; overwriting deletes taste.

Storage next to track favourites in `auth.py` (a `member_album_favs` table or a column —
implementer's call). Every endpoint needs a test per AGENTS.

## Client migration (both at once, that's the point of this doc)

1. **Web**: on sign-in, `sync` with the localStorage list, adopt the merged server list;
   keep localStorage as the anonymous/offline fallback (identity enhances, never gates —
   signed-out likes stay local like today).
2. **Session**: same. `Player.likedAlbums` seeds the first sync from UserDefaults, then
   the server list is authoritative for members; UserDefaults remains the anonymous lane.
   The Session agent commits to shipping this within one build of the endpoints landing —
   ping via a note in this file or AGENTS.

## Coordination notes

- Don't rename the local keys during migration — the seed sync reads them.
- A dir that no longer exists (album renamed/repaired) should be dropped server-side on
  sync rather than 404ing the whole call.
- After both clients adopt: update AGENTS ("record likes are synced; track+album
  favourites share the merge-on-first-sign-in law") and delete this file.
