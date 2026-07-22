# DESIGN — Browse ↔ Now Playing navigation

**Status:** design only, not yet agreed or scheduled. Written 2026-07-22 from a live
walkthrough of `index.html`, `session/Sources/SessionMac/MainWindow.swift`, and
`session/ios/SessioniOS/RootView.swift`.
**The problem (Jason, 2026-07-22):** you're digging in the Attic (or the shelf, or CDs),
tap a track, it starts playing — good, that's the point. You tap **▶ Playing** to see
what's queued. Now you want back to the Attic, exactly where you were — same crate, same
filter, same scroll position — and there's no good way back. "Maybe browser back/forward"
was the opening idea; this doc works out whether that's actually the right shape.

## Today, per surface (as built, verified by reading the code)

Every surface already tries to follow one rule — **tapping a track plays it without
leaving the browsing view** — but only two of three get it right everywhere:

| Surface | Tab/pane model | Tap-to-play leaves the view? | State kept if you leave anyway |
|---|---|---|---|
| Web desktop | `dtab` var, 5 values incl. `playing`; `#playingView`/`#galleryView` toggle `display`, DOM never torn down | No (by design, `index.html:2554`) | Sort + grid/list persist; **filter text force-cleared on every tab switch**; scroll position never restored |
| Mac | `MacDest` enum + `@State dest`, sidebar switch | **Attic: no. Shelf/Genre: yes** — inconsistent (`MainWindow.swift:105-113` vs `117-122`) | SwiftUI `switch dest` likely rebuilds the view on branch change — scroll/search state is not preserved today |
| iPhone | `TabView` + `Nav.tab`; Now Playing is a full-screen **overlay** (`PlayerSheet`), not a tab | **Attic: yes** (`RootView.swift:1017-1020`) — the one surface where it doesn't stay put | N/A (moot until the Attic tap is fixed) — but the tab underneath is never torn down, so it'd be preserved for free |
| iPad | Mac's sidebar shape + ad hoc `nav.shelfSection`/`shelfCrate` handoff | Inherits Mac's split behavior | Same open question as Mac |
| Mobile web (`mobile.html`) | Funnel only — no Attic/Shelf/CDs browsing exists | N/A | N/A — out of scope, doctrine says don't grow it |

Two separate problems, easy to conflate:
1. **A consistency bug** — three different "does tapping a track keep me here?" answers
   across surfaces, when the intended rule is one answer (no).
2. **A missing feature** — even where the rule holds, there's no way to *deliberately*
   visit Now Playing and get back to exactly where you were.

## The real fork: remember a location, or never leave it

**Option A — tab-based Now Playing + remember one "last browsing spot."**
Keep Playing as a peer tab (web `dtab`, Mac `dest`). Add one remembered slot — not a full
history stack — captured the moment you navigate *to* Playing: `{tab, filterText,
scrollTop, selectedGenre/crate}`. Add one small "‹ back to The Attic" affordance (label
reflects whatever was remembered) that restores tab + filter + scroll in one tap. A true
multi-level back/forward stack would only earn its keep if people thread through several
distinct browsing contexts before checking Playing (Attic → an artist's page → Playing →
back → back to Attic root) — worth asking Jason (see Open questions) but my read is this
app's usage is two-place ping-pong, not deep multi-page browsing, so **one remembered
slot, not a stack**, is the right amount of machinery. Simple > clever, per house style.

**Option B — make Now Playing an overlay everywhere, like iPhone already does.**
iPhone's `PlayerSheet` isn't a tab at all — it's a full-screen cover over whatever tab
you're on. Dismiss it (swipe down, tap the handle) and you're back exactly where you
were, automatically, because the tab underneath was **never torn down**. No state to
remember, no back button to build — "back" is just "close." Generalizing this to web and
Mac means Playing stops being a peer of Attic/Stations/CDs/Spots and becomes a transient
view drawn on top of whichever gallery you're browsing.

**Recommendation: Option B.** It's not just simpler to build, it matches what the
codebase already believes: *"browsing is the point of a gallery... the tab bar's ▶ line
shows what started"* (`index.html:2554`), *"you stay in the crate, digging"*
(`MainWindow.swift:118`). Those comments already treat Playing as secondary to browsing —
Option B just stops modeling it as a co-equal destination. It also sidesteps every
scroll/filter-restoration question in the table above, because nothing ever unmounts.
The cost is real but one-time: on web, `#playingView` stops being a `dtab` value and
becomes an overlay panel (CSS: fixed/absolute over `#galleryView`, no different in kind
from the existing `#auth` modal); on Mac, same shape — an overlay over whatever `dest` is
currently showing, not a `dest` case of its own.

If Option B's layout change is more than you want to take on right now, Option A is a
smaller, fully compatible first step — and nothing about building A forecloses moving to
B later, since A's "remembered slot" logic disappears entirely once B lands (there's
nothing to remember when nothing was ever left).

## What ships either way (fix first, regardless of A vs B)

The consistency bug is worth fixing on its own, before either option, since it's a
one-line-per-platform change and the current Session behavior actively contradicts the
product's own stated rule:
- **Mac**: Shelf and Genre album taps do `player.browseAlbum(al); dest = .stage`
  (`MainWindow.swift:105-113`) — drop the `dest = .stage`, matching Attic's `.117-122`.
- **iPhone**: `AtticWalliOS`'s row tap does `player.playAlbum(al); openPlayer()`
  (`RootView.swift:1017-1020`) — drop `openPlayer()`, matching web/Mac Attic.

## Per-surface notes if Option B is chosen

- **Web**: `#playingView` becomes a fixed-position overlay (same visual weight as
  today, just not swapped for `#galleryView` — drawn on top of it). The `▶ Playing` tab
  button and the `#dnp` "what's on" chip both become "open the overlay" instead of "switch
  dtab"; closing it (✕, swipe-down-equivalent, or tapping outside) just hides the overlay.
  `dtab` shrinks to 4 values (stations/cds/attic/spots); the gallery pane's filter text and
  scroll position were never touched by any of this, so they're untouched by construction.
- **Mac**: same shape — `NowPlayingPane` becomes an overlay drawn over whatever `dest`
  shows, not a `dest` case. `TransportBar`'s tap-to-open still works, now opens the overlay
  instead of setting `dest = .stage`.
- **iPad**: already closest to done once Mac's overlay lands, since iPad reuses the Mac
  shape — same overlay, same dismiss.
- **iPhone**: no change needed — this is the pattern already in place. Only the Attic
  tap-through-fix above applies.

## Per-surface notes if Option A is chosen instead

- **Web**: capture `{tab, filterText: $("galFind").value, scrollTop: pane.scrollTop,
  galGenre: S.galGenre}` in `setDtab()` right before switching *to* `"playing"` (skip if
  already coming from `"playing"` — don't overwrite the remembered spot with itself).
  Stop the current unconditional `$("galFind").value = ""` (`index.html:2353`) when the
  destination tab equals the remembered one; restore scrollTop after `renderDeskGallery()`
  paints. Add a "‹ back to {tab label}" affordance in the Playing view header, shown only
  when a remembered spot exists.
- **Mac**: add `@State var lastBrowse: MacDest?`, set it in the sidebar's action right
  before assigning `dest = .stage` (never set when already on `.stage`). Add a small back
  chevron in `NowPlayingPane`. Flag for implementation: confirm whether `switch dest` in
  SwiftUI tears down and rebuilds the branch view (it likely does, since these are plain
  structs, not `.id()`-pinned) — if so, scroll offset and any in-view search field are
  lost on return regardless of the remembered tab, and preserving them needs either
  hoisting that state up to `MainWindow` or layering all destinations in a `ZStack` with
  opacity/hit-testing toggles instead of a `switch` (which is, notably, most of the way to
  Option B already).
- **iPad**: extend the same remembered slot to also carry `shelfSection`/`shelfCrate`.

## Non-goals

- No real `history.pushState`/URL routing — this is app-state navigation, not page
  navigation; a shareable/bookmarkable URL per tab is a separate, much bigger feature
  nobody's asked for.
- No change to `mobile.html` or `dad.html` — neither has crate-browsing to return to.
- No multi-level undo stack (see the Option A note on why one slot is enough) unless
  Jason's answer to the open question below says otherwise.

## Open questions (for Jason)

1. **Option A or B?** My read is B (overlay everywhere, matching iPhone) is the more
   consistent, less-code, more-honest-to-the-product answer — but it's a real layout
   change on web + Mac, where Playing currently looks and feels like a full peer tab.
   If that's a bigger visual departure than you want right now, A is a smaller first cut.
2. **Does browsing ever go more than one level deep before you check Playing?** (e.g.
   Attic → one artist's page → Playing). If yes, a single remembered slot loses the
   artist-page context and only gets you back to the Attic root — worth knowing before
   picking A over a small stack (2-3 deep, still not real browser history).
3. Should the "back to browsing" affordance be universal (always visible on the Playing
   view, no-op if there's nothing to return to) or contextual (only appears when you
   arrived at Playing FROM browsing, not e.g. from a notification or cold start)?
