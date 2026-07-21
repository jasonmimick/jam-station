# DESIGN — Vault Stations (streaming the attic music library)

**Status:** DESIGNED, NOT BUILT — paused 2026-07-20 to capture the plan before building.
**Goal:** turn the ~65 GB of personal music archived on the Time Capsule vault into stations
on jam-station, **without copying it onto the mini** (there isn't room).

This is the **Sourcing** layer for a big local archive — the "attic source adapter" that
AGENTS.md §Family/affiliate has promised but that was never actually built. (Carriage — a
family member's whole station relayed onto your dial — is a separate layer, still coming.)

---

## The problem, precisely

- The vault music lives on the **AFP-mounted Time Capsule**, visible only to the mini's **host
  OS** at `/tmp/tc-afp/attic-vault/` (also SMB at `/tmp/tc`, but **AFP is ~9× faster** — use AFP).
  Structure is artist-organized: `drive-03-inesse-reco/Music/<Artist>/<Album>/<tracks>` (~345
  artists, ~38 GB) and `drive-08-hm500-win/…` (~27 GB music).
- The **jam-brain container** streams from its own docker volume (`slab-jam-brain-music` →
  `/music`). It **cannot see the TC** — the AFP mount lives on macOS and does not propagate into
  the Linux docker VM, so a host bind-mount of the vault into the container will NOT work.
- The mini has **~22 GB free** vs ~65 GB of music, so we **cannot copy the vault into `/music`**
  and reuse the `library` adapter. (Copying a curated ~15 GB slice IS possible and needs zero new
  code — that's the fast fallback if the full build is deferred.)

So streaming *all* of it requires a bridge: something on the host (which can read the vault) that
serves the files to the container over the network.

## The architecture — two small pieces

```
  TC vault (AFP)                    mini host                         jam-brain container
  /tmp/tc-afp/attic-vault  ──────►  attic-server (stdlib http)  ◄────  attic adapter
   Artist/Album/track.mp3           :PORT  /catalog  /file/<path>       (source="attic")
                                    launchd-managed, like jam-inbox     reaches host via
                                                                        host.docker.internal:PORT
```

### 1. Host music server — `tools/attic-server.py` (new)
- Plain-stdlib Python HTTP server, run on the **mini host** (has AFP access) under **launchd**
  (copy the `tools/mini/run.jam.inbox.plist` pattern; KeepAlive). No deps.
- Roots: the vault Music dirs (`drive-03-.../Music`, `drive-08-.../…`). Config the roots by env.
- Endpoints:
  - `GET /catalog.json` — the index: `[{artist, album, path, title}]` (walk once, cache in
    memory; re-walk on a timer or on a `?refresh=1`). Percent-decoded paths relative to a root id.
  - `GET /file/<rootid>/<path>` — streams the actual audio file (support HTTP Range so liquidsoap
    and the browser can seek). Guard against `../` escape like `set_cover` does.
  - `GET /health`.
- Bind to `0.0.0.0:PORT` on a **private** port; reachable from the container as
  `http://host.docker.internal:PORT` (add `--add-host=host.docker.internal:host-gateway` to the
  jam-brain run if the slab runtime doesn't already provide it), and from the tailnet as
  `http://100.91.29.30:PORT`. NEVER expose it through the Cloudflare tunnel — this is private music.

### 2. `attic` source adapter — `brain/app/adapters/attic.py` (new)
- Mirror `adapters/archive.py` (the *remote-URL* pattern, NOT `library.py` which reads local disk).
- Reads `ATTIC_SERVER_URL` (e.g. `http://host.docker.internal:PORT`) from config.
- `pick_tracks(cfg, count)` → hits `/catalog.json`, filters by the channel's query
  (`{"artist": …}`, `{"letter": "A"}`, `{"all": true}`, later `{"genre": …}`), returns track dicts
  whose `url` is the **absolute** `…/file/<rootid>/<path>` on the host server (liquidsoap fetches
  it directly — same as archive.org URLs today).
- Register: add `"attic"` to `STREAMABLE_SOURCES` and (if it queues like library — random batches,
  not whole shows) wire it in `channels.ensure_queue()` the way `library` is. Add to
  `SHOW_ADAPTERS` only if it has show-shaped browsing; otherwise it's a mix/queue source.
- **Private, like `library`** — derive `private = True` (or by source), never tunnel it, so the
  public plane (jam-station.runslab.run) never lists or serves vault stations. Tailnet/members only.
- **Tests** mock the catalog HTTP (httpx.MockTransport, per conftest) and assert pick/queue.

### 3. Stations (the curation on top)
Create via `channels.create_channel(...)` with `source="attic"`:
- **The Vault** — `{"all": true}`, shuffle across everything. The flagship "play it all" station.
- **Artist spotlight** — rotates one artist (either a channel per pinned artist, or one station
  whose query rotates). Cheap, no metadata needed.
- **Later (needs enrichment):** genre and decade stations. The vault has no genre/year metadata;
  covers.py can backfill via MusicBrainz but that's slow and rate-limited across 345 artists. Do it
  as a background pass, then add `shelf-*`-style mix stations.

## Why this shape
- **No copy, no giant mini disk.** Files stay in the vault; only bytes for what's *playing* move.
- **Reuses everything downstream.** Once tracks are annotate-URIs, liquidsoap + icecast + the
  on-demand player + the dial all work unchanged — an adapter is the whole extension point.
- **Host boundary is honest.** The one thing containers can't do (read an AFP mount) is the one
  thing the host server does; everything else stays in the brain. Same split as ripping (the rip
  runs on the host because the container can't see the CD drive).

## Open decisions
1. **Reach from container to host** — confirm `host.docker.internal` resolves under the mini's
   docker runtime; if not, use the tailnet IP `100.91.29.30:PORT` or a slab-provided host alias.
2. **AFP mount persistence** — the vault mount must survive reboot (launchd mount, or an
   `automount`); the attic-server should degrade to "empty catalog / off air", never crash, if the
   vault is absent (same spirit as a guest station being OFF AIR, not broken).
3. **Catalog freshness** — re-walk interval vs manual refresh; 345 artists is a cheap walk.
4. **Metadata** — ship v1 with artist/album/title from the path only (the path IS the tags);
   enrichment (genre/year/cover) is a later pass.
5. **`drive-08` music** — same treatment, add its Music root to the server once drive-03 works.

## Build checklist (for next session)
- [ ] `tools/attic-server.py` + `tools/mini/run.attic.server.plist` (launchd), verify `/catalog.json`
- [ ] confirm container→host reach (`host.docker.internal` or tailnet IP), set `ATTIC_SERVER_URL`
- [ ] `brain/app/adapters/attic.py` + register in `STREAMABLE_SOURCES` / `ensure_queue` + tests
- [ ] create **The Vault** + **Artist spotlight** channels; confirm they mount and stream (private)
- [ ] AGENTS.md: promote the attic adapter from "planned" to "built", note the server + env var
- [ ] (later) enrichment pass → genre/decade stations

## Fast fallback (if the full build is deferred)
Copy a curated ~15 GB slice from the vault into `/music/cds/` (fits the 22 GB free), and it becomes
`library` stations with **zero new code**. Not "all the music," but stations today. Use only as a
stopgap — the host-server path is the real answer.
