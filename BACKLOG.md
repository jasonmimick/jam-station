# jam-station — work items

Live: **https://jam-station.runslab.run** (mac-mini, slab, named Cloudflare tunnel)

## Next up

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
