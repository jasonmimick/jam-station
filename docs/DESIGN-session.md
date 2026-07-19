# DESIGN — Session (was codename "session player")

New native frontends for the station: an **iOS app** and a **desktop app**,
both named **Session** (decided 2026-07-18 — see Branding).
Status: **design & planning — no code yet.** The existing web UIs
(`static/index.html`, `static/mobile.html`) stay intact and keep shipping;
session player is *additive* — new clients on the same brain.

## Why native, and why now

The mobile web app fights iOS for its life: Web Audio pauses playback on
lock, a gestureless AudioContext starts suspended and mutes the element,
PWA installs are second-class. A native iOS app gets true background audio,
real lock-screen/AirPods transport, and (later) CarPlay — the single biggest
UX unlock available to the station. Desktop gets an always-there player that
doesn't live in a browser tab (the Document-PiP mini player was the
proof of demand — Chrome-only was its ceiling).

The "no build step" rule is **web-UI law, not app law**: it exists so the
brain can serve its pages from static files forever. Native apps are a new
kind of surface and get their own minimalism rule instead (see Conventions).

## Scope

Near-full parity — everything a member touches:

| area | in v1 | notes |
|---|---|---|
| Channel dial (photos, private channels for members) | ✅ | `/api/channels` |
| RADIO playback (live stream) | ✅ | `/stream/<slug>` |
| ON DEMAND playback (scrub/jump/rewind a tape) | ✅ | `/api/show` |
| Now playing + queue + history | ✅ | polling, same as web |
| Favourites (synced, playable as a station) | ✅ | `/api/favourites/*` |
| Record shelf / gallery (albums, covers, tracklists) | ✅ | `/api/library/*` |
| NOW RIPPING (LISTEN AND RIP moment) | ✅ | `/api/rip` |
| DJ chat | ❌ deferred | stays on the web UIs for now (decided 2026-07-18) |
| Spot (photograph music in the wild) | ✅ | camera is *better* native; lives in Shelf |
| Listeners ("who's here") | ✅ | `/api/listeners` |
| Sign-in (magic link, passcode, passphrase) | ✅ | see Auth |
| Sleep timer, EQ, share-a-moment links | ✅ | native equivalents |
| Owner admin (members, invite, rotate, revoke) | v1.1 | small, but ship listening first |
| Screensaver / visualizers / "let it dance" | later | desktop-first delight, not core |

Non-goals: replacing the web UIs, any DRM/subscription audio extraction
(hard law), a Windows/Linux desktop build in v1.

## Stack (recommendation — confirm before build)

**One Swift/SwiftUI codebase, two targets: iOS and native macOS.**

- The decisive features — background audio, lock screen, AirPods, CarPlay,
  menu-bar presence on the Mac — are exactly where native Swift is
  strongest and web-wrapper stacks (Electron/Tauri/RN) are weakest.
- The household is all-Apple; the desktop app being macOS-only costs nothing
  today. If a Windows listener ever matters, the web UI already serves them.
- Layout: `player/` in this repo — `player/Core` (shared Swift package:
  API client, models, playback engine, auth/session) plus thin
  `player/iOS` and `player/macOS` app targets. One repo keeps the API
  contract and its clients in one place, same as the web UIs today.

Conventions for the apps (the native analogue of "no build step"):
- **No third-party dependencies to start.** URLSession, AVFoundation,
  SwiftUI, Keychain — the platform ships everything the station needs.
- Apps are **pure API clients**: no local database, no sync engine. Server
  state lives in the brain; taste state (accent, EQ, last channel) lives in
  UserDefaults — the localStorage rule, translated.
- The brain stays the only backend. Anything the apps need that the web UIs
  don't gets a small, boring JSON endpoint, added to `main.py` with a test.

## Architecture

```
iOS app ──┐
macOS app ─┼── HTTPS ──> brain (FastAPI)  ──> icecast/liquidsoap (RADIO)
web UIs ──┘                               ──> archive.org MP3s (ON DEMAND)
                                          ──> /music/* (Jason's CDs, ranged)
```

Nothing new server-side for playback: the apps consume exactly what the
web UIs consume.

### Playback engine (the heart of the design)

Two modes, one engine, mirroring the web UI's mental model:

- **RADIO** — AVPlayer pointed at `/stream/<slug>` (proxied Icecast MP3).
  No seeking; the open connection *is* the listener's presence (the brain
  counts it server-side — no heartbeat needed). Skip = `/api/skip`,
  with the "moves the station for everyone" caveat surfaced in UI copy.
- **ON DEMAND** — `/api/show?channel=` returns the current tape as a full
  tracklist with direct MP3 URLs (archive.org or `/music/...`). Play with
  AVPlayer/AVQueuePlayer: gapless-ish advance, scrub, jump between tracks.
  Presence via `POST /api/presence` heartbeat, same as web.
  Favourites play as an on-demand station (list assembled client-side from
  synced favourites, exactly like the web UI does).

Cross-cutting:
- **Now-playing metadata**: poll `/api/nowplaying` (RADIO) / track index
  (ON DEMAND) → `MPNowPlayingInfoCenter` + `MPRemoteCommandCenter`
  (native MediaSession). Cover art from channel photo / album art.
- **Background audio** (`audio` background mode) on iOS: playback survives
  lock, Control Center transport works. This alone beats mobile.html.
- **Interruptions & routes**: phone call pauses and resumes; AirPods
  removal pauses (system conventions, AVAudioSession).
- **EQ**: AVAudioEngine with a band EQ node *when the user opens EQ* — same
  opt-in philosophy as the web (plain AVPlayer path stays pristine
  otherwise). On iOS this is now safe on lock because we're native.
- **Auto-reconnect**: RADIO stream drops → exponential backoff rejoin,
  matching the web player's behavior.

### Auth for native clients

The brain's model already fits apps beautifully — **identity enhances, it
never gates.** So:

- **Anonymous-first**: the app works signed-out (public channels, radio,
  on demand). No login wall, ever.
- **Sign-in inside the app**, three doors, same as web:
  1. **Passcode** — email + 8-char code typed into a native sheet →
     `POST /api/auth/key`. Simplest, ship first.
  2. **Passphrase** — `POST /api/auth/passphrase` for members who set one.
  3. **Magic link** — the emailed `/k/<token>` link opens the app via a
     universal link (requires an `apple-app-site-association` file served
     by the brain — small backend addendum, v1.1).
- **Session**: the 30-day session cookie, stored in the app's
  URLSession cookie jar (persisted via HTTPCookieStorage; token value
  mirrored to Keychain as backup). No token scheme, no OAuth — the
  cookie already *is* a bearer credential and URLSession speaks cookies
  natively. Zero backend change for v1.
- `GET /api/me` on launch decides signed-in UI (favourites sync, private
  channels, listeners, shelf).

### Backend addenda (small, all additive)

| change | for | when |
|---|---|---|
| `apple-app-site-association` route | magic-link → app deep link | v1.1 |
| `/api/rip` poll is fine; consider `Cache-Control` hints | NOW RIPPING panel | v1 nice-to-have |
| Owner-admin endpoints already exist | admin screens | v1.1 |
| Nothing else | — | polling model carries over wholesale |

No websockets in v1 — the web UIs poll and feel fine; the apps poll on the
same cadences and back off when backgrounded.

## The Tuner (core concept — Jason, 2026-07-18)

Session is built on the stereo-component metaphor. **Session is the
receiver; the Tuner is the component inside it that selects what you
hear.** Two levels, like a real tuner:

1. **Session tunes into a station** — the jam-radio backend. The brain's
   base URL is NOT hardwired: it's the station Session is tuned to
   (default `jam-station.runslab.run`, stored in settings). This is one
   config field today and the entire future tomorrow — when dad's Mac in
   Florida becomes a sovereign station (DESIGN-family-radio.md,
   DESIGN-network.md), Session already knows how to tune to it. Saved
   stations = **presets**, exactly like FM presets on a stereo. The
   family-radio doc's open question "what does dad's family install to
   listen?" (D5) has a natural answer: Session.
2. **Within a station, the Tuner picks the channel** — the photo wall /
   station list. The *surface* is called the Tuner; the *interaction* is
   the dial (you turn the dial on a tuner). All existing UI vocabulary
   (on air, gate, the dial) survives inside it.

Naming rule in UI copy: **Tuner** is the place, **tune** is the verb,
**preset** is a saved station. v1 ships with one station and no preset
UI — but Core treats the station URL as data from day one, so the
network future costs nothing now.

## Design language

**Evolve the identity, don't port the layout.** The station's soul —
departures-board / split-flap now-playing, broadcast-dark default with a
light mode, the accent color, station photo dial, "gate" typography —
carries into native. But layouts are rethought per platform:

### iOS — screen map

Tab bar, three tabs + the persistent player:

1. **Tuner** — the station wall (photo grid); the dial you turn. Tap =
   tune (RADIO). Long-press / detail = channel card: now playing, queue,
   history, "play this tape ON DEMAND" switch.
2. **Shelf** — the record gallery, newest first (folder-mtime order),
   NOW RIPPING takeover banner when a disc is ripping; album → cover,
   year, tracklist, play. Spot lives here as the camera button
   ("photograph music in the wild" → identified → onto the Spotted shelf).
3. **You** — sign in / member card, favourites (playable), listen history,
   sleep timer, EQ, settings (accent, appearance).

(No DJ tab — DJ chat is web-only for now; the tab bar has room when it
comes over.)

Persistent **mini-player bar** above the tab bar (art, split-flap title,
play/pause) → swipes up into the full player: big art, split-flap
now-playing, transport (mode-aware: live vs scrub), listeners chip,
favourite ♥, share-the-moment, sleep timer, EQ.

### macOS — window map

**The menu-bar player ships first** (decided 2026-07-18) — the true
successor to the Document-PiP mini player: a menu-bar icon → popover with
album art, split-flap now-playing, transport, a compact Tuner (channel
switcher), volume, and a scrubber in ON DEMAND (usage is 50/50, so both
modes are first-class even here). Media keys via `MPRemoteCommandCenter`.
No Dock icon required.

The **main window** follows immediately — it is a *want*, not a someday:

- **Left rail**: the Tuner (station list w/ photos, live listener dots).
- **Center**: the stage — big now-playing, split-flap board, transport,
  tape tracklist in ON DEMAND, NOW RIPPING takeover.
- **Right rail**: tabs for Shelf / History / You. (DJ chat joins when it
  comes over from the web.)

Never stacks — panes collapse to rails, honoring the existing law.
Later: visualizer screensaver as a delight pass.

## Branding

**The apps are named "Session"** (Jason, 2026-07-18). It names the
*players*, not the station — the station rename (Shortwave et al., see
BACKLOG) stays its own decision; "Session" works either way ("Session,
tuned to Shortwave" reads fine). The word carries the right music DNA:
jam session, recording session, live session. One asterisk for the
record: a privacy messenger app is also called Session — irrelevant for
personally-distributed apps with no App Store presence.

Directory: `session/` (Core + iOS + macOS targets). Icon set and accent
default isolated in one config point regardless, because names have
changed before.

## Phasing

- **P0 — the engine + menu-bar player (macOS)**: playback core (RADIO +
  ON DEMAND, auto-reconnect, now-playing polling) inside the menu-bar
  popover: art, split-flap, transport, compact Tuner, scrubber, media
  keys. Signed-out only. Daily value on Jason's Mac in the first phase.
- **P1 — the desktop main window**: three-pane (dial / stage / rails),
  NOW RIPPING takeover, shelf + history. Sign-in lands here
  (passcode/passphrase) because the shelf and private channels are
  members-only. Favourites sync + play. This phase is the shareable
  family .app.
- **P2 — the iOS app**: tab bar (Tuner / Shelf / You), background audio,
  lock-screen transport, Spot camera, favourites. Jason's phone via free
  signing.
- **P3 — polish + parked items**: EQ, sleep timer, share-the-moment,
  visualizer/screensaver, owner admin. Parked until wanted: DJ chat in
  the apps, magic-link universal links, CarPlay (needs paid account).

P1 before P2 because the desktop version is explicitly wanted *now*;
the Core package is shared, so iOS in P2 is mostly UI work. Swappable
if phone hunger strikes first.

## Decided (2026-07-18)

- **Name: Session.** Names the apps; the station rename stays a separate
  BACKLOG item.
- **The Tuner** is the channel-picking surface in every Session UI, and
  the station URL is data ("Session tunes into a station") — see The
  Tuner section.
- **Stack: SwiftUI, one codebase, iOS + macOS targets.**
- **Code lives in `session/` in this repo** (Core package + two app
  targets).
- **Tooling**: Xcode toolchain, but day-to-day via terminal —
  `make ios` / `make mac` wrapping xcodebuild + devicectl.
- **Dev machine: euler** for now; the mini stays a pure server.
- **Usage is 50/50 RADIO / ON DEMAND** → both modes co-equal everywhere,
  including the menu-bar popover; neither is the "advanced" mode.
- **Desktop order: menu-bar player first, main window immediately after**
  — the window is explicitly wanted, not deferred.
- **DJ chat: not in the apps for now** — stays on the web UIs; revisit
  after P2.
- **Distribution**: desktop .app shared with family Macs; family phones
  stay on mobile web; iOS app = Jason's phone, free personal-team
  signing (7-day resign, fine during active dev). No paid Apple account.
  CarPlay/TestFlight/universal links parked behind that decision.

## Open questions

None blocking. Discoverable at build time: Jason's iPhone iOS version
(sets the deployment target), euler's Xcode version. Next design step:
detailed UI design for the P0 menu-bar player (popover layout, split-flap
treatment in a native context, channel-switcher interaction).
