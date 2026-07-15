#!/usr/bin/env bash
# Watch the CD drive and ingest any disc that appears. Put a CD in, walk away; it rips into
# the catalog and ejects itself so you can drop in the next one. The whole shelf, one at a time.
#
# WHY A POLLER AND NOT AN EVENT: macOS has diskarbitration notifications, but they need a
# running CoreFoundation loop and a signed helper to be reliable across login sessions. A 10s
# poll of `drutil status` is boring, has no moving parts, and survives anything. A CD is not
# a low-latency event source — nobody minds a 10-second wait for a disc that takes 4 minutes
# to rip.
#
# IDEMPOTENT BY DISC SIGNATURE: the ledger remembers which discs are already done (hashed from
# the track TOC), so re-inserting a disc, or the watcher restarting mid-rip, never double-rips.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
LEDGER=${LEDGER:-$HOME/.jam-ripped}
INTERVAL=${INTERVAL:-10}
touch "$LEDGER"

log() { printf '%s  %s\n' "$(date '+%H:%M:%S')" "$*"; }

disc_dir() {
  ls -d /Volumes/*/ 2>/dev/null | while read -r v; do
    compgen -G "$v"'*.aiff' >/dev/null && { echo "$v"; break; }
  done
}

# A disc's identity is its track list: names + byte sizes. Same disc -> same signature, every
# time, on any drive. Cheaper and more stable than a MusicBrainz id, and it needs no network.
disc_sig() {
  ls -la "$1"*.aiff 2>/dev/null | awk '{print $5, $NF}' | shasum | cut -d' ' -f1
}

log "watching the drive every ${INTERVAL}s — ledger: $LEDGER"
while true; do
  d=$(disc_dir || true)
  if [ -n "${d:-}" ]; then
    sig=$(disc_sig "$d")
    if [ -n "$sig" ] && ! grep -q "^$sig" "$LEDGER" 2>/dev/null; then
      # A JUST-INSERTED disc is still settling — macOS mounts it, then Gracenote renames the
      # tracks and the files appear progressively. Rip mid-enumeration and you capture a
      # partial disc AND ledger its partial signature forever, so it never gets re-ripped.
      # Require the signature to hold still across a few seconds before committing to a rip.
      sleep 4
      if [ "$sig" != "$(disc_sig "$d")" ]; then
        log "disc still settling — will pick it up once it stops changing"
        continue
      fi
      log "new disc — ripping"
      # -y unattended, -e eject when done. rip-cd identifies via MusicBrainz on its own.
      if bash "$HERE/rip-cd.sh" -y -e 2>&1 | sed 's/^/    /'; then
        echo "$sig  $(date '+%Y-%m-%d %H:%M')" >> "$LEDGER"
        log "done — ledger updated"
      else
        log "rip FAILED — leaving disc in, will retry next tick"
      fi
    fi
  fi
  sleep "$INTERVAL"
done
