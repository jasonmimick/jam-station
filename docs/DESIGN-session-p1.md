# DESIGN — Session P1: the main window (macOS)

Parent: `DESIGN-session.md` · sibling: `DESIGN-session-p0.md` (menu-bar
player). Status: **design — no code.**

P1 is the full desktop Session: the station's three-pane desktop UI,
re-composed as a native macOS window on the same playback engine the
menu-bar player built in P0. It is also where **sign-in** lands — which
lights up the shelf, private channels, favourites, listeners, and the
**CD** source. This phase produces the shareable family .app.

Design law carries over from P0: **Session invents no look of its own** —
every token, control, and row pattern comes from `static/index.html`.

## Window anatomy

```
┌─●●●──────────────────────────────────────────────────────────────┐
│ [J] JAM-STATION   RADIO|TAPE|CD    ● ON AIR · GRATEFUL DEAD  ◐ 👤│  signage header
├──────────────────────────────────────────────────────────────────┤
│ ● NOW RIPPING — Still Life (Talking) · track 4/9 ▓▓▓▓░░░░        │  rip bar
├───────────────┬──────────────────────────────┬───────────────────┤
│ TUNER    find │  NOW PLAYING        ● ON AIR │ SHELF HIST YOU    │
│ ♥ Favourites  │  [art]  Scarlet Begonias     │ ┌────┐┌────┐      │
│ ▸ Grateful D. │         Grateful Dead ·      │ │    ││    │      │
│   Phish   ● 1 │         Barton Hall '77      │ └────┘└────┘      │
│   Jazz        │         256 kbps · mp3 · live│ ┌────┐┌────┐      │
│   Newgrass    │   ◂◂  [▶]  ▸▸  ♥  EQ   vol  │ │    ││    │      │
│   Klezmer     │  ──────────────────────────  │ └────┘└────┘      │
│   70s Fusion  │  Barton Hall — 1977-05-08    │  the record       │
│   NO MUSIC    │  ✓ Loser          ✓ played   │  gallery          │
│  ── PRIVATE ─ │  ▶ Scarlet Begonias    NOW   │  (grid/list)      │
│  ♫ My CDs PRIV│    Fire on the Mountain      │                   │
│               │    Estimated Prophet         │                   │
├───────────────┴──────────────────────────────┴───────────────────┤
 (panes resize by dragging hairlines; either side collapses to a rail)
```

### Signage header

The web masthead as the window chrome: yellow bar, traffic lights
sitting on it, mark + wordmark, the **Radio / Tape / CD** source modes
(CD enabled once signed in), status (`ON AIR · <CHANNEL>` red with dot ·
`TUNING IN…` while buffering), listener tally, then the web's icon
buttons: accent palette, theme ☾/☀, and **You** (person icon — sign-in
state lives behind it, mirroring the web's member button).

### Rip bar — LISTEN AND RIP, first-class

The strip under the header, exactly like the web's `#ripBar`: idle it's
a quiet sunk line (last disc added); ripping it goes **yellow with the
red inset bar and blinking dot**, shows disc · track x/y, and fills a
subtle progress. When the rip completes it flips to "**on the shelf** —
<album>" and the Shelf tab shows the new arrival first (folder mtime IS
date-added). If nothing is playing, the center stage does the takeover
(cover, big progress — the web's idle-takeover behavior, kept).

### Left pane — the Tuner

The web's departures list, verbatim: `.dep` rows with 42px art thumbs
(the art-mono/tint/invert treatments carry over), name, sub-line
(current show), green live-listener dots, `NO MUSIC` dead rows,
**Favourites as a red-heart station** at top (`dep.favs`), and — once
signed in — the private section with yellow `PRIV` chips. Find-as-you-
type filter in the pane header.

### Center pane — the stage

The web's board: eyebrow + red ON AIR lamp, album tile with gradient-
monogram fallback, big clean-swap title, byline, meta (mono year,
source link), spec line. Transport: square 2px buttons, yellow go,
bordered ♥ like, EQ toggle (AVAudioEngine band EQ, opt-in), volume.
Tape/CD add the scrubber. Below: the schedule — show name, progress
hairline, `.r` tracklist rows (✓ played · blue-inset NOW · upcoming),
click a row to jump (Tape/CD). Radio shows the same list read-only with
skip-confirm semantics.

### Right pane — Shelf / History / You

The web's pill tabs (`.dtabs` style), three of them (DJ joins later):

- **SHELF** — the record gallery: search, grid/list toggle (`.vtog`),
  album covers with the pressed-sleeve gradient + monogram fallback,
  date-added italic captions, newest first. Click an album → tracklist
  → play = the **CD** source. A disc mid-rip appears as the first card,
  live. Spot lives here too (drop a photo → identified → Spotted).
  Members-only: signed out, the tab shows the sign-in nudge instead.
- **HISTORY** — the play log (`/api/history`): channel-labelled rows,
  whole network or filtered to one channel.
- **YOU** — signed out: the three doors (passcode / passphrase / "email
  me my link"), native fields, same normalize rules. Signed in: member
  card (name, email), favourites list (playable, red hearts, synced),
  sleep timer, sign out. Owner tools (add person, rotate, revoke) come
  in v1.1 — the web keeps them meanwhile.

### Pane behavior

Exactly the web's laws: three columns always — no stacking at any
window width; side panes resize by dragging the hairlines (widths in
UserDefaults, like the web's localStorage `--c1/--c2`); either side
collapses to a 26px labelled rail, click to reopen. Minimum window size
keeps the stage usable (~900×600).

## Sign-in (the P1 backend touchpoint — zero new endpoints)

Person icon or You tab → sheet with the three doors:
1. **Passcode**: email + code → `POST /api/auth/key` (normalize
   UPPERCASE, strip spaces/dashes — same `normalize_code` contract).
2. **Passphrase**: email + passphrase → `POST /api/auth/passphrase`.
3. **Email me my link**: `POST /api/auth/login` — the mail arrives with
   the magic link (web) and the passcode works in the app.
Success = 30-day session cookie in URLSession's cookie jar (persisted;
mirrored to Keychain). `GET /api/me` on launch restores state. Signing
in re-fetches `/api/channels` (private appear) and syncs favourites
(`/api/favourites/sync` — push local, pull merged, same as web).

## What signing in lights up

| signed out | signed in |
|---|---|
| public channels, Radio + Tape | + private channels (PRIV chips) |
| CD mode disabled (dimmed) | + the Shelf and the CD source |
| favourites local-only | favourites synced + playable anywhere |
| empty listeners room | who's listening, by name |

## Engine notes (shared with P0)

One playback engine, three sources: Radio (stream proxy), Tape
(`/api/show` tracklist), CD (`/api/library/album` + `/music/*` — Range
seeks work natively). The menu-bar popover and the window are two views
of the same state; closing the window keeps playing (Session stays in
the menu bar — Dock icon optional, default hidden, a setting).

## Out of scope for P1

DJ chat (parked), owner admin (v1.1), Spot camera (iOS P2 — desktop
gets file-drop), screensaver/visualizers, share-the-moment (P3),
CarPlay/universal links (parked with the paid account).
