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

- [ ] **Mini-player for laptops.** A compact, always-visible player so the station
      keeps running while you work in another tab/window. Options, roughly in order
      of effort:
      1. **Compact mode in-page** — collapse to a slim bar (art, title, transport,
         station switcher). Cheap, works everywhere, no install.
      2. **Picture-in-Picture** — the browser's Document PiP API gives a real
         floating always-on-top window from a web app. Chrome/Edge only today, but
         it's exactly the "mini-player" shape and needs no native app.
      3. **Menu-bar app** — a true macOS status-bar player. Most native, most work;
         only worth it if 1 and 2 aren't enough.
      Note: MediaSession already puts the track + transport on the OS media widget
      and lock screen, so some of this need may already be met — check that first
      before building anything.

- [ ] **Load your own music.** The single unlock that lights up both `70s Fusion`
      and `BeBop` (currently shown honestly as "NO MUSIC"). Needs the music files on
      the mac-mini and a slab volume mount. This is also the *only* way to get real
      bebop/commercial fusion — it isn't on the Archive (live taper tapes only) and
      streaming it publicly would need real licensing (see fusion101 research).

- [ ] **launchd services.** The cloudflared tunnel and the mini's slab daemon both
      run under `nohup`. **A reboot takes the station down** until someone SSHes in.

## Known issues

- [ ] Untitled Archive tapes fall back to "Track 3". We mine the item description
      for a setlist when the files carry no titles, but some tapes have no setlist
      anywhere (the description is taper gear notes). Could try the `.txt` files
      some items ship.
- [ ] Skipping in RADIO mode moves the station for *everyone* listening. Correct
      for a broadcast, but worth a confirm if this is ever shared.

## Ideas

- [ ] Branching workflows for the DJ (queue a whole set, not one show).
- [ ] "Surprise me" — random station.
- [ ] Favourites → export as a playlist / share a list.
- [ ] Auth, so favourites follow you off this browser (localStorage today).
      The favourites array is already shaped to POST straight into a table.

## Done

- Departures-board UI (Schiphol), dark + light, split-flap now-playing, gate logo
- RADIO (live icecast) + ON DEMAND (browser plays Archive MP3s: jump, scrub, rewind)
- Favourites (localStorage) as an on-demand station
- 15 stations, every Archive collection id verified against the live API
- Channels come on air by themselves (liquidsoap self-reloads on list change)
- MediaSession (lock screen + headphones), stream auto-reconnect, PWA installable
- 256kbps (was 128), 5-band EQ, sleep timer, share-the-moment deep links
