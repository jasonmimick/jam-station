# DESIGN — Contributor identity: Tailscale IS the identity

**Status:** design only, not yet built. Written 2026-07-22 after a live security gap:
Session's Send Music panel ships with a single shared, embedded SSH key — anyone who
finds the public `/session/download` link gets the same key, with write access to the
inbox. Fixing that properly, rather than patching around it, turns into the actual
feature this project has wanted since the personal-radio page shipped: **"their
contributed slice up top is a TODO (needs upload attribution)"** (AGENTS.md).
**The one-line idea:** stop trusting a secret baked into a downloadable app. Trust the
**network** instead — a contributor is already authenticated the moment their traffic
arrives over the tailnet, because Tailscale itself knows exactly who they are. Verified
live: `tailscale whois 100.101.108.11` → `mark2m@icloud.com`, no ambiguity, no secret
involved at all.

## What's wrong with tonight's design

`tools/jam-outbox.command` and Session's Send Music both bake in `dad_key`, an SSH key
pre-authorized on a dedicated `mark` account. That key is the **only** thing gating who
can write into the inbox — and it's sitting inside a zip anyone can download from a
public URL. The blast radius is bounded (that account can only write one folder, no
shell, no other access) but it's a real hole, and it also means every upload is
attributed to the same generic `mark` account regardless of who actually sent it —
there's no way to know "Dad sent this" vs. "anyone with the zip sent this."

## The design: identity comes from the tailnet, not from a bearer secret

**Core claim:** if a contributor's traffic reaches the mini AT ALL over Tailscale, the
host can ask Tailscale itself "who is this" and get a real, unspoofable answer — the
contributor's login email, the same identity Tailscale already verified when they
signed in. No key to embed, no key to steal, no key to rotate.

**The mapping is deliberately the simplest possible thing**: a member's jam-station
email and their Tailscale login email are assumed to be **the same address** — true by
construction, since Jason is the one sending both the jam-station invite and the
Tailscale share/invite to that person. No new mapping table, no second identity to
manage. `auth.member_by_handle`-style lookup already keys everything off `email`; this
reuses that directly.

## Architecture

Replace the whole SSH+rsync+dedicated-account path with a small host-side daemon, same
family as `attic-server.py` / `jam-cdd` / `jam-atticd` — stdlib, launchd, runs on the
host because it needs something Docker can't see (here: the host's own `tailscaled`,
which is what actually knows peer identities; a container has no visibility into who's
on the tailnet unless tailscale itself runs inside it, which is unnecessary complexity
this avoids entirely).

```
tools/mini/jam-contribd.py     NEW — host daemon, stdlib http.server, launchd
                                (run.jam.contrib.plist, alongside run.attic.server.plist)
  BINDS ONLY the host's tailscale interface (100.91.29.30), not 0.0.0.0 — this
  endpoint must be UNREACHABLE from the public internet or the tunnel, same
  discipline as attic-server's port 8517 never crossing the tunnel.

  POST /contribute            multipart: a zip of the folder, nothing else needed
    1. Get the request's source IP (the TCP peer — real, not a header, so it
       can't be spoofed by the client).
    2. `tailscale whois <src-ip>` -> the connecting Tailscale login email.
       (Shells out to /Applications/Tailscale.app/Contents/MacOS/Tailscale whois,
       same binary-path gotcha as everywhere else Tailscale is scripted here.)
    3. Ask the brain "is this email an approved member?" — GET
       /api/internal/member-by-email (new, tiny, LOCALHOST-only endpoint the
       daemon calls; reuses auth.member_by_handle's underlying query, just
       keyed on email instead of handle). No match = 403, nothing written,
       nothing attempted.
    4. Match: unzip into /music/inbox/<member-handle>/<folder-name>, exactly
       where jam-inbox.sh already looks — NO CHANGE to jam-inbox.sh's import
       logic, channel creation, or ledger. Only the ARRIVAL mechanism changes.
    5. NEW: record the attribution — a `contributions` table (member_email,
       slug, folder_name, created_at) — this is the actual payoff, and what
       finally lets a personal radio page show "their contributed slice."
```

**What disappears entirely**: the `mark` macOS account, its SSH key, the
`Match User mark` sshd_config block, `Resources/dad_key` (and the gitignore rule for
it), `session/Sources/SessionMac/ContributeView.swift`'s key-staging code. Nobody ever
generates, ships, or embeds a secret again. The three gotchas AGENTS.md just gained
about SSH access lists, `sysadminctl`, and openrsync's `--chmod` all become moot — they
were fighting problems that only existed because of the SSH-account approach.

**What the client (Session's Send Music, `jam-outbox` v2) does instead**: zip the
folder, `POST` it to `http://100.91.29.30:8518/contribute` (reachable ONLY because the
contributor is already on the tailnet — that reachability IS the auth, nothing else
needed client-side). No key, no `ssh -i`, no `rsync`. Genuinely less client code than
today, not more.

## Why this also closes tonight's hole for free

Anyone can still download Session from the public page — that was never really the
problem, the EMBEDDED KEY was. With no key baked into the app at all, a stranger who
downloads Session and clicks Send Music simply can't reach `jam-contribd` (wrong
network — not on the tailnet) or, if they somehow were on some tailnet, their identity
would resolve to an email that isn't an approved member and get flatly rejected. There
is no longer a secret to have leaked in the first place, so the public-download-page
question stops being a security question at all.

## Attribution surfacing (the actual product win)

- Personal radio (`/<handle>`) gains its promised "their contributed slice" section:
  `SELECT * FROM contributions WHERE member_email=?`, joined to the channels those
  folders became.
- Station metadata could show "contributed by Dad" the same way CD imports show
  provenance elsewhere in this codebase.
- Later, trivially: an owner-facing view of "who's sent what" — the very thing the
  earlier Session conversation flagged wanting (a revoke/manage view), except there's
  no per-person key to revoke anymore — revoking a contributor is just removing their
  jam-station membership, which already exists as owner tooling.

## Migration

1. Build `jam-contribd.py` + the `contributions` table + the internal member-lookup
   endpoint. Test with Dad's REAL tailscale identity (`mark2m@icloud.com`) end to end.
2. Update Session's Send Music and `tools/jam-outbox.command` to POST instead of rsync;
   ship both.
3. Once confirmed working, retire: the `mark` account, its SSH key, the sshd_config
   `Match User` block, and `Resources/dad_key` (delete, don't just gitignore).
4. Dad needs to update Session once (auto-update, now that it exists, handles this) —
   no new install step, no new key, nothing for him to do beyond clicking "Update."

## Decisions (settled 2026-07-22, no longer open)

1. **Multiple contributors, same email-identity assumption**: confirmed as the intended
   shape. Jason personally invites each contributor to both jam-station and the tailnet,
   so the two emails matching is true by construction, not an assumption that needs
   policing.
2. **Port for `jam-contribd`**: **8518** — next free slot after 8517 (music shelf server)
   and 8519 (reserved for shoebox), per AGENTS.md's existing port ledger.
3. **A rejected (non-member) request gets silence, not an error.** The daemon accepts
   the connection, reads the whois result, and if it's not an approved member, drops
   the connection with no response body and no distinguishing status — indistinguishable
   from nothing listening at all. No information leak about what's running on that port
   or why a request failed.
