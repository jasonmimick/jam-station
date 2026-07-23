# The Jam-ineer: Dev role

**Audience:** an agent building features on jam-station's backend/full-stack (brain,
adapters, schema, tools). Read `AGENTS.md` first for architecture and conventions;
this is about the workflow discipline that keeps changes safe to ship.

## How to deploy this part of the system

```bash
cd brain && pytest                            # must be green — non-negotiable
git add <only the files you touched>
git commit -m "..."                           # scoped, one concern per commit
git push origin main
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_euler jason@jasons-mac-mini \
  'cd ~/business/jam-station && git pull --ff-only'
slab -N jasons-mac-mini deploy jam-brain
curl -s https://jam-station.runslab.run/health   # verify it's actually live
```
Pushing to GitHub is not deploying. The mini needs its own pull, and `slab deploy`
needs its own run, before anything you wrote is actually serving traffic. If the pull
hits a conflict on a file you didn't mean to touch (it happens — a host-side script
gets edited directly outside git sometimes), check the diff before discarding either
side; don't blindly force one direction.

## When to check in before proceeding

- **Schema changes, new tables, anything touching real member data** — go ahead and
  build/test it, but flag before running a migration-shaped change against the LIVE
  database (as opposed to the test DB pytest already isolates).
- **A design that's accumulating its own new infrastructure** (a new daemon, a new
  binding/networking layer, a new identity system) to solve a problem — pause and
  surface the simpler alternative rather than pushing further in; see below.
- **Anything that changes what a downloadable client can do with a secret** — ask
  before shipping, this is exactly the class of thing that bit this project once.
- **Ambiguous production data** (which of two rows is the "real" one, which email is
  actually in use) — ask, don't guess; a wrong guess on identity is expensive to unwind.
- Ordinary feature work, bug fixes, and anything covered by an existing test — just
  build it, test it, ship it. Don't ask permission for things the test suite can verify.

## Tests are not optional, and they catch real things

`cd brain && pytest` must be green before any commit — not a formality. Tonight it
caught two genuinely deploy-breaking bugs before either reached production: a stray
semicolon inside a SQL *comment* (the schema init does a naive `SCHEMA.split(";")`,
so English punctuation inside a `--` comment corrupts the next statement) would have
crashed every fresh database init. Both were invisible from reading the code; only
running the suite surfaced them. Every new endpoint gets a real test, including the
negative case (hidden from anonymous, hidden from the wrong host header, rejects a bad
token) — not just the happy path.

## Verify for real, not "this should work"

Tonight's contributor-upload work was tested by: minting a real token, uploading a
real zip, over the real public HTTPS endpoint, confirming the file landed and the
channel appeared — twice, once for each client. When a GUI interaction couldn't be
driven headlessly (SwiftUI's drag-and-drop), the same networking code was extracted
into a standalone harness and run for real rather than left as "should be identical to
what I already tested." Simulated confidence is not the same as demonstrated
confidence — when you can run the actual thing, run it.

## Never let a secret ride into git, or into a public download

This project got burned once already: an SSH key embedded in a downloadable app,
served from a public URL, usable by anyone who found the link. Before committing
anything key/token/credential-shaped, check it's gitignored; before shipping anything
downloadable, ask what happens if a stranger gets a copy of it. The fix that actually
held up was structural (per-member bearer tokens tied to an existing signed-in
session, nothing embedded at all) — not "gate the download page better."

## Reach for the boring pattern before the clever one

A host daemon doing Tailscale-identity verification was a real, working idea — until
it started accumulating its own bugs (a platform-specific socket-bind failure that
resisted reasonable debugging) and its own ambiguities (whose email matches whose).
The fix that shipped was the standard SaaS shape: sign in with what already exists,
mint a bearer token, done. When a design starts requiring new infrastructure to solve
a problem existing infrastructure could solve more simply, that's the signal to
switch, not to debug harder.

## Match what's already here

Stdlib only for host tools (no `requests`, no third-party deps) — this project runs on
whatever's on the Mac already. No ORM; raw SQL through the `?`→`%s` facade. Minimal
dependencies everywhere. Before introducing a new pattern, check whether an existing
one (a helper function, a table shape, a test fixture) already does the job.

## Respect other people's in-flight work

`git status` before editing a shared file, especially `session/` — other devs are
often mid-build there. Stage and commit only what's actually yours; if an unrelated
file shows as dirty, leave it alone unless you know why it's dirty. Scoped, atomic
commits with a clear "why" beat one big commit that mixes concerns.
