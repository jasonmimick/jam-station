# The Jam-ineer: UX/Design role

**Audience:** an agent working on jam-station's UI/UX — the web desktop, mobile funnel,
or any new surface. Read `AGENTS.md` first for the conventions already in force; this
is about the process that keeps a new surface from looking or behaving invented.

## How to "deploy" design work

Design work here has two stages, and skipping the first is the most common mistake:

1. **Write a `docs/DESIGN-<name>.md` doc before writing UI code** — this project starts
   every real feature this way (`DESIGN-vinyl.md`, `DESIGN-navigation.md`, etc.). State
   the problem, the options, a recommendation with its real tradeoff, and open
   questions — then let the doc get read/approved before touching a component.
2. **Build against the SAME design tokens already in `index.html`** (or the relevant
   Session `Theme`) — colors, spacing, type scale, the placard/monogram system for
   missing art. Never invent a new visual language for a new panel; it should be
   indistinguishable from something that shipped months ago.

```bash
# after a doc is approved and code is written: same deploy path as any brain change
git push origin main
ssh ... 'cd ~/business/jam-station && git pull --ff-only'
slab -N jasons-mac-mini deploy jam-brain
```

## When to check in before proceeding

- **Before writing any code for a nontrivial UX shift** — a new navigation model, a new
  panel, anything that changes how an existing flow behaves. The design doc IS the
  check-in; don't skip straight to implementation on a real interaction change.
- **When you find a cross-platform inconsistency** (see below) — surface it and ask
  which surface is "correct" rather than picking one silently; sometimes the divergence
  was intentional.
- **Anything that bends a stated non-goal** (mobile web is a funnel and shouldn't grow;
  no bulk art prefetch) — flag it as bending the rule, don't quietly treat the rule as
  obsolete.
- Small, contained visual fixes matching an existing pattern — just build them.

## Check every surface, not just the one you're looking at

This project has three-plus live surfaces (web desktop, Session Mac, Session
iPhone/iPad) implementing the same interactions independently. It's easy for one to
quietly diverge from the others without anyone noticing — a real audit found web and
Mac's Attic view correctly "stay in the crate" on tap, while iPhone's Attic view jumped
straight to Now Playing, and Mac's Shelf/Genre view did too. None of these were
deliberate; they'd just each been built at different times by different reasoning.
Before declaring "the rule" for how an interaction works, check it against every
surface that implements it.

## The recommendation is not the whole menu

When a UX design has more than one reasonable shape, present ONE clear recommendation
with its real tradeoff, plus the genuine alternative if there is one — not an
exhaustive survey of every option considered. The DESIGN doc for browse/Now-Playing
navigation is the model: two real options (remember a browsing slot vs. make Now
Playing a dismissible overlay everywhere), a stated recommendation, and why — not five
options with no opinion attached.

## Respect the small details that make it feel considered

Filter-as-you-type, not a poll (a past gallery bug: it "worked" only by accident via a
30-second refresh). Scroll position and in-progress filters surviving a tab switch.
Placards over invented "not found" art. These aren't decoration — they're the
difference between a feature that feels native to the product and one that feels
bolted on. When building something new, look for the equivalent existing detail nearby
and match it rather than shipping the default.
