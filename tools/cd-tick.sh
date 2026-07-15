#!/bin/bash
# ONE TICK of the CD watcher — run by the agent's wake loop, not a mini-side daemon.
#
# The launchd poller (cd-watch.sh) kept wedging: a running process would stop noticing new
# discs for reasons that never reproduced when traced by hand. So we flip it around — the
# agent's background loop, which already wakes on a schedule, drives each check itself. One
# tick = "is a rip going? is there a new disc? if so, start it." It prints a STATE line the
# loop reads to pick its next wakeup: fast (a rip or a fresh disc in play) or slow (idle).
#
# This only runs while the agent's loop is alive — that's the trade for reliability and for
# Jason seeing each step. rip-cd.sh still does the actual work (lock, MusicBrainz, eject,
# ledger); this only decides and triggers.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
RIPCD="$HERE/rip-cd.sh"
LEDGER=${LEDGER:-$HOME/.jam-ripped}

disc_sig() { ls -la "$1"*.aiff 2>/dev/null | awk '{print $5, $NF}' | shasum | cut -d' ' -f1 || true; }
drive_id() { df "$1" 2>/dev/null | awk 'NR==2{print $1}' | sed 's#^/dev/##; s/s[0-9]*$//'; }
# bracket-safe .aiff check — a quoted glob keeps "[Disc 1]" literal (compgen -G would read it
# as a character class and miss the disc entirely).
has_aiff() { local f; for f in "$1"*.aiff; do [ -e "$f" ] && return 0; done; return 1; }

# 1) a rip already running? report progress and let the loop check back soon.
if pgrep -f rip-cd.sh >/dev/null 2>&1; then
  tn=$(pgrep -af lame 2>/dev/null | grep -oE 'tn [0-9]+/[0-9]+' | head -1)
  echo "STATE=RIPPING ${tn:-starting}"
  exit 0
fi

# 2) a new, settled disc on any drive? start it.
for v in /Volumes/*/; do
  has_aiff "$v" || continue
  sig=$(disc_sig "$v"); [ -n "$sig" ] || continue
  grep -q "^$sig" "$LEDGER" 2>/dev/null && continue          # already ripped, ever
  drive=$(drive_id "$v")
  [ -d "/tmp/jam-rip-${drive:-single}.lock" ] && { echo "STATE=RIPPING (lock $drive)"; exit 0; }
  # settle: a just-inserted disc is still being enumerated; don't rip a partial one
  sleep 3
  [ "$sig" = "$(disc_sig "$v")" ] || { echo "STATE=SETTLING $v"; exit 0; }
  nohup bash "$RIPCD" -y -e -d "$v" > "/tmp/rip-${drive:-x}.log" 2>&1 &
  disown
  echo "STATE=STARTED drive=${drive:-?} vol=${v}"
  exit 0
done

echo "STATE=IDLE"
