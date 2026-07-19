# DESIGN — Session P0: the menu-bar player (macOS)

Parent: `DESIGN-session.md`. Status: **design — no code.**
The first shippable piece of Session: a menu-bar player that delivers
daily listening value on Jason's Mac and forces the playback core to be
solid before any big UI exists.

## The idea in one line

The station's signage, on a smaller sign: a popover that drops out of the
menu bar with now-playing, transport, the source selector, and a compact
Tuner — nothing else.

## Design system: the station's, verbatim (Jason, 2026-07-18)

Session invents NO look of its own. Every visual token comes from the
web UI (`static/index.html`):

- **Signage yellow `#FFD200` masthead** with near-black `#12120C` text;
  the source modes ride inside it, bordered 2px, inverting when active —
  exactly the web's Radio/On-Demand toggle.
- **Dark theme** board `#0F0F11` / panel `#17171A` / line `#2B2B31`;
  **light theme** equivalents — the popover honors the same
  dark/light/auto choice as the web, and the accent system carries over
  (yellow is the default signage color; the user's custom accent
  re-tints it, same as `--yellow`/`--flap-ink` on the web).
- **Square signage controls**: 2px borders, 2px radius, uppercase
  letter-spaced labels; hover/active go **blue `#3B82F6`**; the play
  button is the filled **yellow "go"** square. Red `#F0402F` = ON AIR
  lamp; green `#2FD16A` = live listeners.
- **Type**: Helvetica Neue signage; `ui-monospace` for spec lines,
  times, and years (`256 kbps · mp3 · live`).
- **Title changes are a clean swap** (fade), matching the web player —
  the split-flap lives in the logo mark, not the now-playing text.
- Channel lists are **departure rows**: name + status/live count, the
  active row carrying a 3px inset accent bar.

Mockup: see the published artifact (Radio + Tape states, both themes).

## Source selector: RADIO / TAPE / CD (approved 2026-07-18)

Real receivers label their source switch TUNER / TAPE / CD / AUX. The
project already calls Archive shows *tapes*, and the shelf is literally
ripped CDs. So playback sources wear stereo names in Session:

- **RADIO** — the live broadcast (`/stream/<slug>`). No seeking; skip
  moves the station for everyone (confirm dialog, per the known issue).
- **TAPE** — the current taper-live show as a playable tracklist
  (`/api/show`): scrub, jump, rewind. What the web calls ON DEMAND.
- **CD** — an album off the shelf played on demand (`/api/library/*`).
  Members-only, so the CD input lights up in P1 with sign-in; in P0 the
  selector shows RADIO / TAPE.

Same engine, one selector. Usage is 50/50 radio/on-demand, so the
selector sits on the main face, not in a menu.

**REVISED during the P0 build (Jason, 2026-07-18): no mode toggle.**
The masthead selector is gone; the choice is a contextual button on the
face instead — on Radio it reads **"LISTEN TO THE TAPE"** (step off the
broadcast onto your own copy of the show), on Tape it reads **"BACK TO
THE RADIO — LIVE"** (red, rejoin the broadcast). Radio/Tape/CD survive
as engine *sources* and design vocabulary, not as a UI switch; CD will
arrive in P1 as "play from the shelf", not a masthead mode.

## Popover anatomy (~350pt wide)

```
┌────────────────────────────────────┐
│ [J] JAM-STATION  RADIO|TAPE|CD    │  signage-yellow masthead + modes
├────────────────────────────────────┤
│ NOW PLAYING            ● ON AIR    │  eyebrow + red lamp (radio)
│ [art]  Scarlet Begonias            │  album tile + title (clean swap)
│        Grateful Dead · Barton '77  │  byline
│        256 kbps · mp3 · live       │  mono spec line
│  ◂◂   [▶ go]   ▸▸        🔊──●──  │  square controls, yellow go, vol
│  3:12 ────●──────────── 9:41      │  scrubber — TAPE only
├────────────────────────────────────┤
│ TUNER                              │  .lbl
│ ▸ Grateful Dead              ● 2  │  departure rows, inset accent
│   Phish                      ● 1  │  bar on the tuned row, green
│   Jazz                            │  live-listener dots,
│   70s Fusion            NO MUSIC  │  honest states
├────────────────────────────────────┤
│ ⌘←→ tune · space ⏯            ⚙  │  footer: hints + settings
└────────────────────────────────────┘
```

- **Masthead** — the station Session is tuned to (station = data, per
  the Tuner concept), with the source modes riding in the yellow bar
  exactly like the web's mode toggle. CD sits dimmed until P1 sign-in.
- **Now playing** — the web's board, miniaturized: eyebrow, red ON AIR
  lamp (radio only), album tile with the gradient-monogram fallback,
  title as a clean swap, mono spec line. Buffering reads `TUNING IN…`,
  unreachable reads `OFF AIR` — the web's own vocabulary.
- **Transport** — RADIO: ◂◂ disabled, ▸▸ = skip-with-confirm ("moves
  the station for everyone — skip?"). TAPE: prev/next track, and the
  scrubber row appears.
- **Compact Tuner** — departure rows with live-listener dots and honest
  states (`NO MUSIC`). Click = tune. No photo grid at this size (that's
  the main window's Tuner).
- **Footer** — keyboard hints + settings gear; ⧉ open-main-window joins
  in P1.

## Menu-bar icon

Template (monochrome) glyph — a small broadcast/antenna mark. States:
- idle (not playing): plain glyph
- playing: glyph + tiny dot (menu bar stays quiet — no marquee text,
  no color; the popover is the display)
Right-click = quick menu: Play/Pause · Tune ▸ (channel submenu) ·
Open Session (P1) · Quit. Left-click = the faceplate.

## Input

- **Media keys / AirPods** via `MPRemoteCommandCenter`; now-playing +
  art via `MPNowPlayingInfoCenter` (Control Center shows Session like
  any real player).
- Popover keyboard: `space` play/pause · `↑↓` move in Tuner · `return`
  tune · `⌘←/→` previous/next channel · `⌘,` settings.
- Scrubber: drag, plus `←/→` nudge ±10s in TAPE.

## Behavior

- **Polling**: popover open → `/api/nowplaying` every 3s, `/api/queue`
  on open; popover closed but playing → every 15s (keeps lock-screen/
  Control Center info and the board fresh for next open). Not playing →
  no polling at all.
- **Presence**: RADIO needs none (the open stream IS the presence);
  TAPE posts `/api/presence` every 30s while playing.
- **Reconnect**: RADIO drop → exponential backoff (1s → 2s → 4s … cap
  30s), status reads `TUNING IN…` (the web's word); TAPE track failure →
  try next track once, then pause honestly.
- **Reduce Motion**: the ON AIR lamp stops blinking; the title swap is
  already just a fade.

## Settings (one small sheet)

- **Station** — the URL Session is tuned to (default
  `https://jam-station.runslab.run`). The future preset list starts as
  this one field.
- **Accent** — the web's signage-colour system, verbatim: the same eight
  curated accents (Amber #FFD200 default, Sodium #FF8C1A, Crimson
  #FF3B3B, Magenta #FF4FA3, Teal #12D6B6, Cyan #38BDF8, Lime #86E01E,
  Violet #A98BFF) plus a custom colour, with the on-colour computed
  from luminance (>0.45 → near-black #12120C text, else white) so no
  choice can make the masthead unreadable. Stored in UserDefaults
  (Session's localStorage), independent per device like the web.
- **Launch at login** (SMAppService).
- Sign-in lives in P1 with the main window — P0 is anonymous, which the
  brain fully supports (public channels only; private channels appear
  in the Tuner after P1 sign-in).

## Out of scope for P0 (parked deliberately)

EQ, sleep timer, share-the-moment, NOW RIPPING surface, shelf, Spot,
favourites, sign-in, main window. The faceplate does one thing: play the
station beautifully.
