# DESIGN — Session P2: the iOS app

Parent: `DESIGN-session.md` · siblings: `DESIGN-session-p0.md` (menu-bar),
`DESIGN-session-p1.md` (main window). Status: **design — no code.**

The phone Session. Native is the whole point here: **playback survives
the lock screen** — the one thing mobile.html can never promise — plus
real lock-screen/AirPods transport and a camera that opens instantly for
Spot. Distribution: Jason's phone via free personal-team signing; family
phones stay on mobile.html (decided 2026-07-18).

## Design system: the handheld expression

Same tokens, softer shapes — this is `mobile.html`'s language, kept:
rounded 12px covers and 10–14px controls (vs. the desktop's square
signage), pill buttons, floating mini-player, bottom sheets with grab
handles, the big yellow circular play. Colors, type roles, badges
(green matched / yellow wishlist / gray unknown), live-listener green,
accent system with computed on-color — identical to the web. Dark and
light, following the system or the in-app choice.

## Structure

Native tab bar (accent-tinted): **Tuner · Shelf · You** — with the
**mini-player floating above it** whenever something plays, and the
**full player** as a swipe-up sheet. (No DJ tab — parked; the tab bar
has room when it comes over.)

```
┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐
│ [J] JAM-STATION ◎ │  │ ── grab ──        │  │ [J] JAM-STATION ◎ │
│ ┌───────┐┌───────┐│  │   ┌─────────┐     │  │ ┌ SPOT A SONG ──┐ │
│ │photo  ││photo  ││  │   │ big art │     │  │ │ 📷 point at it │ │
│ │GRATEFUL││PHISH ││  │   └─────────┘     │  │ └───────────────┘ │
│ │DEAD ●2││   ●1  ││  │ Scarlet Begonias  │  │ ●NOW RIPPING──────│
│ └───────┘└───────┘│  │ Grateful Dead     │  │ ┌───────┐┌───────┐│
│ ┌───────┐┌───────┐│  │ 256KBPS·MP3·LIVE  │  │ │ rip   ││ cover ││
│ │JAZZ   ││NEWGRAS││  │ RADIO|TAPE|CD     │  │ └───────┘└───────┘│
│ └───────┘└───────┘│  │ ●─────────── 9:41 │  │   the shelf grid  │
│ ┌───────┐┌───────┐│  │  ⏮   (▶)   ⏭  ♥  │  │                   │
├───────────────────┤  │                   │  ├───────────────────┤
│ ♪ Scarlet Beg… ▶  │  │                   │  │ ♪ Scarlet Beg… ▶  │
├───────────────────┤  │                   │  ├───────────────────┤
│  TUNER SHELF YOU  │  └───────────────────┘  │  TUNER SHELF YOU  │
└───────────────────┘     the full player     └───────────────────┘
```

### Tuner tab

The station wall: 2-up photo cards (station art with the art-treatment
filters), name, live-listener badge, `NO MUSIC` dead state, Favourites
card first (red heart) when signed in, PRIV chip on private channels.
Tap = tune (Radio). Long-press = the channel card: now playing, what's
coming, history, and **"Play this tape"** (jump to Tape on this show).
Find-as-you-type at top.

### The player (mini + full)

- **Mini**: floating pill above the tab bar — art, title marquee,
  play/pause. Tap or swipe up → full player.
- **Full**: grab handle, big art, clean-swap title, byline, mono spec
  line (`256 kbps · mp3 · live` / `on demand`), the **Radio | Tape |
  CD** source modes, scrubber + track x/y on Tape/CD, transport with
  the 72pt yellow circular play, ♥ like, and the skip-asks-first
  confirm on Radio. Channel name is a chip that pops back to the Tuner.

### Shelf tab

**Spot rides on top** — the dashed "SPOT A SONG" button opens the
camera directly (native = instant, no file picker), photo → identified
→ Spotted card with badge (matched/wishlist/unknown). Below: NOW
RIPPING banner card when a disc is ripping (live progress, then
"on the shelf"), then the record grid — covers, monogram fallbacks,
date-added order, search. Tap an album → tracklist sheet → play = CD
source. Signed out: the honest nudge ("Your ripped CDs live here once
you sign in"), Spotted still local-visible.

### You tab

Signed out: the three doors in a native sheet (passcode / passphrase /
"email me my link" — same normalize rules, same endpoints as P1).
Signed in: member card, playable favourites (red hearts, synced),
listen history, sleep timer, appearance (theme + the eight signage
accents + custom), sign out.

## Native platform work (the reason P2 exists)

- **Background audio** entitlement; AVAudioSession `.playback` —
  lock the phone, the station keeps playing. EQ (opt-in, AVAudioEngine)
  is now lock-safe too — the web's hardest iOS gotcha, dissolved.
- **Lock screen / Control Center / AirPods**: MPNowPlayingInfoCenter
  (art included) + MPRemoteCommandCenter (play/pause/next; disable
  seek commands on Radio).
- **Interruptions & routes**: calls duck/pause and resume; unplugging
  pauses. System conventions, free with AVAudioSession.
- **Polling discipline**: foreground cadences match the web; backgrounded,
  no polling — lock-screen info updates on track change via the already-
  playing stream's metadata timer (15s, low duty).
- **Presence**: Radio = the stream connection; Tape/CD = heartbeat 30s
  foregrounded only.

## Out of scope for P2

DJ chat (parked), owner admin (web), CarPlay + universal links (parked
with the paid account), share-the-moment + sleep-timer polish if it
slips (P3 catches them), iPad layout (later — it would want the P1
three-pane, not the phone tabs).
