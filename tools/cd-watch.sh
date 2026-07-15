#!/usr/bin/env bash
# Watch every CD drive the host has and ingest whatever appears. Put a disc in, walk away; it
# rips into the catalog and ejects itself. Load two drives and both rip at once — one ripper
# agent per drive, never two on the same one.
#
# WHY A POLLER AND NOT AN EVENT: macOS has diskarbitration notifications, but they need a
# running CoreFoundation loop and a signed helper to be reliable across login sessions. A 10s
# poll is boring, has no moving parts, and survives anything. A CD is not a low-latency event
# source — nobody minds a 10s wait for a disc that takes four minutes to rip.
#
# WHO OWNS WHAT: this watcher only DECIDES ("here's a new, settled disc on a free drive");
# rip-cd.sh does the ripping, holds the per-drive lock, and ledgers its own success. So the
# watcher never tracks a background job — it just doesn't re-launch a drive whose lock is held
# or whose disc is already in the ledger.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
LEDGER=${LEDGER:-$HOME/.jam-ripped}
INTERVAL=${INTERVAL:-10}
touch "$LEDGER"

log() { printf '%s  %s\n' "$(date '+%H:%M:%S')" "$*"; }

# A disc's identity is its track list: sizes + names, hashed. Same disc -> same signature on
# any drive, no network. MUST match rip-cd.sh's computation so the ledger lines up.
# `|| true`: a disc pulled between the glob check and here must not kill the watcher (set -e).
disc_sig() { ls -la "$1"*.aiff 2>/dev/null | awk '{print $5, $NF}' | shasum | cut -d' ' -f1 || true; }
# The physical drive behind a volume — the lock unit. Matches rip-cd.sh's `drive`.
drive_id() { df "$1" 2>/dev/null | awk 'NR==2{print $1}' | sed 's#^/dev/##; s/s[0-9]*$//'; }

log "watching all drives every ${INTERVAL}s — ledger: $LEDGER"
while true; do
  # Every audio-CD volume mounted right now — one per loaded drive. Not just the first: a host
  # can have several drives, and each gets serviced independently.
  for v in /Volumes/*/; do
    compgen -G "$v"'*.aiff' >/dev/null 2>&1 || continue
    sig=$(disc_sig "$v"); [ -n "$sig" ] || continue
    grep -q "^$sig" "$LEDGER" 2>/dev/null && continue        # already ripped, ever
    drive=$(drive_id "$v")
    [ -d "/tmp/jam-rip-${drive:-single}.lock" ] && continue  # a ripper already owns this drive

    # A just-inserted disc is still settling — macOS mounts it, then Gracenote renames the
    # tracks and files appear progressively. Rip mid-enumeration and you capture a partial disc
    # and ledger its partial signature forever. Require the signature to hold still first.
    sleep 4
    [ "$sig" = "$(disc_sig "$v")" ] || { log "disc on ${drive:-?} still settling"; continue; }

    log "new disc on drive ${drive:-?} — ripping ($v)"
    # Background, so a second loaded drive isn't blocked behind this rip. rip-cd takes the
    # per-drive lock, identifies via MusicBrainz, ejects (-e), and ledgers itself on success.
    ( bash "$HERE/rip-cd.sh" -y -e -d "$v" 2>&1 | sed "s/^/    [${drive:-?}] /" ) &
  done
  sleep "$INTERVAL"
done
