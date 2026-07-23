# The Jam-ineer: Session (native app) role

**Audience:** an agent working on `session/` — the native Mac/iPhone/iPad apps. Read
`AGENTS.md`'s Session section and `docs/DESIGN-session*.md` first; this is the
process/gotcha layer specific to building the native client.

## How to deploy this part of the system

```bash
cd session
make run              # fast loop: build (debug-ish release), open the app locally
make mac-release       # ships a universal build to the LIVE /session/download endpoint
make ios-sim           # build + run in the iOS Simulator
make ios-phone         # build + install on Jason's actual iPhone
make ios-ipad          # build + install on Jason's actual iPad
```
Never open Xcode to iterate — the Makefile is the whole loop. **A device install is
only real if you verify it**: `make ios-phone`/`ios-ipad` grep the installer's own
output for the literal `App installed` line and print the build number from the
device's own app listing. A truncated or piped install log has previously masked a
failed build while a STALE bundle silently reinstalled — never trust an install
without that explicit confirmation line.

`make mac-release` changes what's live at `/session/download` immediately — there's no
separate "deploy" step after it, the zip lands straight in the brain's music volume and
is served from then on. Treat running it with the same weight as any other production
deploy.

## When to check in before proceeding

- **Anything that would embed a secret/key/token into a build** — don't. This project
  had exactly that (`dad_key`, baked into every public download) turn into a real
  security hole. Reuse the app's own signed-in session (the cookie already lives in
  `HTTPCookieStorage`) for anything requiring identity instead.
- **A self-modifying operation** (the auto-updater's download-and-replace-self dance)
  — test it against a **disposable copy of the app**, never the main working build.
  It's a genuinely destructive operation (it deletes and replaces its own bundle) and
  deserves that caution every time it's touched.
- **A new top-level feature/panel** — same rule as the UX doc: write or extend a
  `docs/DESIGN-session-*.md` note before building if it's more than a small addition.
- Bug fixes, matching an existing pattern, small additive views — just build and test.

## macOS's bundled tools are not always what you'd assume

- **`rsync` is `openrsync` (BSD), not GNU rsync 3.x** — the common numeric `--chmod`
  form is rejected outright, and even the symbolic form didn't reliably override a
  source file's existing permissions in testing. If a permissions problem shows up,
  fix it at the SOURCE (`chmod` before the transfer), don't reach for rsync flags.
- **No App Store means ad-hoc signing (`codesign --force --sign -`), and that's fine
  for Mac** — unlike iOS's free-provisioning-profile builds (which genuinely expire
  after 7 days), an ad-hoc-signed Mac app just needs one right-click-Open past
  Gatekeeper and then runs indefinitely. Don't assume the iOS distribution friction
  applies to Mac; it doesn't.
- A platform-specific bug (a Python 3.9 socket bind failure, hit building a companion
  host daemon) can resist reasonable debugging even when the exact same code works
  fine elsewhere. It's fine to redesign around a stuck platform quirk rather than
  chase it indefinitely — see `docs/DESIGN-contributor-identity.md`'s abandoned
  daemon for exactly this call being made.

## Match `Theme`, use `@EnvironmentObject`, don't reinvent networking

New views should pull `Theme` the same way every existing view does and read
`Player`/`SessionCore` state via `@EnvironmentObject`, not by threading extra
parameters through initializers unless there's a specific reason to keep a view fully
self-contained. For anything hitting the brain, look at `SessionCore/API.swift` first
— multipart uploads, auth, and the session-cookie pattern are already solved there;
extend that file rather than rebuilding networking inline in a view when the call
belongs at the API layer.

## Swift specifics worth knowing before they cost you a build

- `??` does not support an `await` on its right-hand side inside the autoclosure —
  write the `if let / else { await }` explicitly instead.
- `Process` is the right tool for shelling out to `zip`, `chmod`, or anything else a
  sibling shell tool already does — mirror the exact same command the shell version
  uses rather than reimplementing the logic in Swift.
- Verify a build actually compiles (`swift build -c release`) before assuming a Swift
  edit is correct — small things (an autoclosure, an optional binding) fail late and
  don't announce themselves in review.
