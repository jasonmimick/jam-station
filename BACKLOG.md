# jam-station — work items

Live: **https://jam-station.runslab.run** (mac-mini, slab, named Cloudflare tunnel)

## Next up

- [ ] **"LISTEN AND RIP"** — the product concept for the CD flow: the station is something you
      listen to AND grow by feeding it discs. As a disc rips, the now-playing panel becomes
      "NOW RIPPING" (done 2026-07-16 — panel takeover when idle). Expand: surface it as a mode /
      tagline, and make the rip a first-class moment (cover, progress, "added to your shelf").

- [ ] **RENAME. "jam-station" is wrong and we know it.** The product outgrew the name: it
      plays ragtime, klezmer, gamelan, newgrass, funk. "Jam" boxes it into one genre it left
      behind. Deferred 2026-07-13 (needs more thought), but **it gets more expensive every
      day** — repo, slab app names, DNS, the Cloudflare tunnel, docs, UI, PWA icons.

      Checked and **available on `.fm`** (the radio TLD):
      | name | for | against |
      |---|---|---|
      | **shortwave.fm** ⭐ | the romance of a faint voice arriving from far away — *literally the product* (dad in Florida, heard in NY). Genre-proof, which is exactly why "jam" broke. | a known email startup is called Shortwave (different category) |
      | callsign.fm | a station's identity; maps onto subdomains (`dad.callsign.fm`) AND the auth work | an **identity-verification company** is called Callsign — awkward while building identity |
      | longwave.fm | same romance, cleaner mindshare | less culturally loaded |
      | kindred.fm | names the *relationship*, not the tech — lovely for a family network | abandons the radio metaphor the UI is built on |
      | airwave.fm | clean, obvious | generic |

      Taken: skywave.* · relay.fm (a podcast network) · dial.fm · onair.fm · tuner.fm ·
      wavelength.fm · transmit.fm · tower.fm · static.fm

      **Jason floated "uberjam" (2026-07-14, half asleep).** Recorded, with two honest
      objections: (1) it KEEPS "jam" — which is the precise thing we said was broken, since
      the station now plays ragtime, klezmer and gamelan; (2) *Überjam* is a John Scofield
      album (2002) — a great record and very on-brand for the jam-jazz world, but it's
      someone else's title and would be a permanent asterisk. Worth revisiting awake.

      Recommendation: **Shortwave**. The vocabulary keeps working — *on air · call sign ·
      affiliate · carriage · relay · the dial.*

- [ ] **Load your own music.** *Status 2026-07-19: Jason is digging out old hard drives and
      MP3 CDs this week. Note: MP3 CDs are DATA discs — the watcher ignores them (has_aiff);
      ingest those by copying files off the mounted volume, or teach cd-tick a data-disc
      path if there turn out to be many.* The single unlock that lights up both `70s Fusion`
      and `BeBop` (currently shown honestly as "NO MUSIC"). Needs the music files on
      the mac-mini and a slab volume mount. This is also the *only* way to get real
      bebop/commercial fusion — it isn't on the Archive (live taper tapes only) and
      streaming it publicly would need real licensing (see fusion101 research).

- [ ] **launchd services.** The cloudflared tunnel and the mini's slab daemon both
      run under `nohup`. **A reboot takes the station down** until someone SSHes in.
      *2026-07-20: attic-server joined the nohup club* — its launchd agent + `~/bin/jam-atticd`
      are installed and ready, but **Jason must grant Full Disk Access to `~/bin/jam-atticd`**
      (System Settings → Privacy & Security → Full Disk Access; launchd is silently denied the
      AFP vault without it, exactly like jam-cdd). Then:
      `pkill -f attic-server.py && launchctl load ~/Library/LaunchAgents/run.attic.server.plist`.
      Also still TODO: launchd auto-mount for the TC AFP share itself (a reboot unmounts the
      vault → vault stations OFF AIR until `mount_afp`).

## Known issues

- [ ] Untitled Archive tapes fall back to "Track 3". We mine the item description
      for a setlist when the files carry no titles, but some tapes have no setlist
      anywhere (the description is taper gear notes). Could try the `.txt` files
      some items ship.
- [ ] Skipping in RADIO mode moves the station for *everyone* listening. Correct
      for a broadcast, but worth a confirm if this is ever shared.

## Ideas

- [ ] **Agent-built channels — share a link + instructions, an AI agent interviews the
      person and builds their station** (Jason, 2026-07-20; roadmap). You send a family
      member a link with instructions for an AI agent; the agent asks "what do you want on
      your radio?" and creates channels for them — no menus, just a conversation. Natural
      extension of the DJ (`dj.py` already does tool-calling `create_channel`): give a
      newcomer an onboarding agent that turns "I love '90s alt-rock and my old bootlegs"
      into a personal dial. Pairs with personal-radio handles (`/<handle>`) and the
      contributor inbox — the agent could even guide the folder upload. Later.

- [ ] **/admin — the engineer's booth** (Jason, 2026-07-19): owner-only page with live
      system status (icecast mounts up?, liquidsoap reachable?, queue depth + prefetch per
      channel, Postgres health, music-volume disk usage, last backup age, rip status,
      presence) plus a **"Station Engineer" chat** — a dj.py-style Claude tool loop with
      OPS tools instead of music tools: report status, skip/flush a queue, resync genre
      channels, kick covers, read the brain's own logs. Honest scope note: the brain can't
      restart containers (it IS one) — host-level actions stay with slab/ssh; the engineer
      diagnoses and advises there. Reuses the existing chat UI pattern.

- [ ] **Stylize the station photos** (Jason, 2026-07-18 — idea only, don't build yet):
      run the channel-art photos through a unifying treatment so the wall reads as one
      set — e.g. inverted, duotone/tinted toward the accent, or black-and-white with a
      colour wash. Could be a CSS filter per tile (cheap, reversible, theme-aware) or
      baked into the JPGs at curation time. Play with it later.
- [ ] Branching workflows for the DJ (queue a whole set, not one show).
- [ ] "Surprise me" — random station.
- [ ] Favourites → export as a playlist / share a list.
- [ ] Auth, so favourites follow you off this browser (localStorage today).
      The favourites array is already shaped to POST straight into a table.

## Done

- 2026-07-18: **No more Unknown Albums.** The three mystery rips identified and renamed
  (North Sea Jazz Festival sampler via CDDB with 0.8s offset proof; Road to You -> Pat
  Metheny Group; Grammavision sampler -> Various Artists). cd-name now falls back to
  gnudb/CDDB when MusicBrainz has never seen the disc; fuzzy matching refuses <5-track
  discs and tightens to 2s drift under 8 tracks — never a wrong name.

- 2026-07-18: **Invite email works end-to-end** (owner-tested): Add person → the station
  emails their magic link + passcode (Gmail SMTP); passcode can be owner-chosen; rotate
  re-sends a fresh pair
- 2026-07-17: **Mini player** (masthead ⧉ — Document PiP: now-playing, transport, pocket
  visualizer; Chrome/Edge). Menu-bar app only if this isn't enough.
- 2026-07-17: Collapsible Tunes/DJ panes (slim rails); narrow desktop windows keep the
  three columns (stacked pseudo-mobile fallback removed)
- 2026-07-17: Screensaver (▓ / 3 idle min): Bars · Ring · Scope, pick or Rotate; "Let it
  dance" — accent colour sways with the music; gallery shows date added
- 2026-07-17: CD naming hardened — exact MusicBrainz disc ID first, fuzzy only with
  per-track offset proof (the *Are You Experienced* → "Fiddler's Green" bug); the
  misnamed rip repaired in place
- 2026-07-17: pytest isolated into a `_test` Postgres DB — it was silently writing into
  the live database since the Postgres migration
- Departures-board UI (Schiphol), dark + light, split-flap now-playing, gate logo
- RADIO (live icecast) + ON DEMAND (browser plays Archive MP3s: jump, scrub, rewind)
- Favourites (localStorage) as an on-demand station
- 15 stations, every Archive collection id verified against the live API
- Channels come on air by themselves (liquidsoap self-reloads on list change)
- MediaSession (lock screen + headphones), stream auto-reconnect, PWA installable
- 256kbps (was 128), 5-band EQ, sleep timer, share-the-moment deep links
