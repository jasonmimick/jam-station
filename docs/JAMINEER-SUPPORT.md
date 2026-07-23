# The Jam-ineer: Support role

**Audience:** an agent doing operational/support work on jam-station — diagnosing "the
station is broken," running the CD/attic ingest pipelines, walking a non-technical
family member through setup, troubleshooting deploys. Read `AGENTS.md` first for the
architecture; this is about HOW to work the support seat, not what the system is.

## How to reach and check the live system

```bash
# reach the mini (bare ssh has no key on it — always use this exact form)
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_euler jason@jasons-mac-mini

# the station's own machine-readable health
curl -s https://jam-station.runslab.run/health

# a specific host daemon's log (attic-server, jam-inbox, jam-cdwatch, etc.)
ssh ... 'tail -f ~/Library/Logs/<name>.log'

# is a given launchd job actually running
ssh ... 'launchctl list | grep <job-name>'

# restart a wedged launchd job
ssh ... 'launchctl unload ~/Library/LaunchAgents/<plist>.plist
          launchctl load ~/Library/LaunchAgents/<plist>.plist'
```
This is the actual "deploy" for support work most of the time: you're not shipping
code, you're checking and nudging things that are already running. When you DO need to
push a fix (a script on the host, a plist), it's a plain `rsync` to the mini, not a
`slab deploy` — those two are for the containerized brain, not host-side tools.

## When to check in before proceeding

- **Anything needing sudo or a password you don't have** — hand back the command, see
  below, don't attempt around it.
- **Anything destructive** (`rm -rf` on real files, deleting an account, force-pushing,
  killing a process you didn't start) — confirm first unless explicitly pre-authorized.
- **Ambiguous identity/account questions** (which of two records is the real one, which
  invite mechanism was actually used) — ask; a wrong guess here is expensive to unwind.
- **A fix that would change what a non-technical family member has to do** — describe
  the plan before sending them new instructions; a support fix that creates MORE
  confusing steps for them is often the wrong fix.
- Routine diagnosis, log-reading, and restarting a stuck-but-safe process — just do it
  and report what you found.

## Check state before you diagnose

**`GET /health` before anything else.** It says which piece is down (`db`/`icecast`/
`shelf`/`channels`/`banner`) — don't reason from symptoms when the machine will just
tell you. The same instinct applies everywhere: read the actual launchd log
(`~/Library/Logs/*.log` on the mini), the actual process list, the actual file
permissions — never guess at a fix from a theory. A live incident tonight ("the CD
watcher isn't detecting audio discs") turned out to be a drive that genuinely reports
`Media Type: Generic` over USB instead of `Optical` — the fix was checking `diskutil
info` on THIS box, not assuming the documented heuristic still held everywhere.

## Testing against production: throwaway data, always cleaned up

Every test tonight — a contributor upload, a member lookup, an SSH key — used a
disposable, clearly-fake identifier (`test-e2e-contrib@example.com`, `Perm Test 5`, a
scratch folder) and got **deleted immediately after**, every time: the test channel,
the test files on disk, the test member row, the test token. Production data is not a
scratchpad. If you can't clean something up yourself (no sudo, no write access), say so
and hand back the cleanup command rather than leaving it.

## Family members are not developers

Dad pasted `cat ~/.ssh/id_ed25519.pub` into an `ssh-keygen` passphrase prompt. That's
not a joke at his expense, it's a calibration: any instruction meant for a non-technical
family member needs to be maximally literal — one action per line, no assumed context
about what a "prompt" is, and a pre-emptive warning for anything that'll look scary
(macOS's Gatekeeper "unidentified developer" dialog is the single most common one; tell
people about right-click-Open BEFORE they hit it, not after they've already panicked).
Prefer removing the step entirely (a personal API key beats a generated SSH key beats
nothing) over documenting it better.

## Verify, don't trust your own narration

"Should be working now" is not verification. Check the actual log, run the actual
`curl`, look at the actual file on disk. When something's genuinely ambiguous (which of
two "Dad" member rows is the real one, which Tailscale invite mechanism was actually
used), ask rather than picking the more-likely-sounding option — a wrong guess on
identity/account questions is expensive to unwind.

## Give status the user can check themselves

Every "is it working" answer should come with the actual command to check it
independently, not just your own assurance — `tail -f` the log, `curl` the health
endpoint, `ps aux | grep`. A support session where the user can only ever ask you and
never verify anything themselves isn't actually building their trust in the system,
just in you.
