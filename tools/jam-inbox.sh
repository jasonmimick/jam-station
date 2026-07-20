#!/usr/bin/env bash
# jam-inbox — turn a dropped folder into a station. The contributor half of the family radio.
#
# A family member (over Tailscale) rsyncs a music folder into ~/jam-inbox on the mini:
#     rsync -av "Guitar Festival Chicago 2007" jasons-mac-mini:jam-inbox/
# This watcher notices each new, SETTLED top-level folder and:
#   1) copies its audio into the jam-brain container's /music volume (docker cp — the same
#      door the CD ripper uses; slab volumes are per-app, so a copy is how files get in),
#   2) creates a library channel named after the folder (source=library, query.folders),
#   3) ledgers it so it's imported exactly once.
# liquidsoap self-reloads on the channel-list change, so the new station just comes on air.
#
# WHY A POLLER: same boring philosophy as the CD watcher — a 20s poll has no moving parts and
# survives anything. "Settled" = size unchanged across one interval, so we never import a
# folder mid-rsync. Runs on the mini host (needs docker); drive via launchd or the agent loop.
set -uo pipefail

INBOX=${INBOX:-$HOME/jam-inbox}
BRAIN=${BRAIN:-slab-jam-brain}
LEDGER=${LEDGER:-$HOME/.jam-inbox-imported}
INTERVAL=${INTERVAL:-20}
AUDIO_RE='\.(mp3|flac|m4a|wma|wav|aac|ogg|aiff|shn|ape|m4p)$'
export PATH=$PATH:/usr/local/bin
mkdir -p "$INBOX"; touch "$LEDGER"

slugify() { echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]\+/-/g; s/^-//; s/-$//' | cut -c1-48; }
dir_size() { du -sk "$1" 2>/dev/null | cut -f1; }

import_folder() {
  local dir="$1" name slug tracks
  name=$(basename "$dir")
  slug="inbox-$(slugify "$name")"
  grep -qx "$slug" "$LEDGER" 2>/dev/null && return 0            # already imported
  tracks=$(find "$dir" -type f 2>/dev/null | grep -iE "$AUDIO_RE" | wc -l | tr -d ' ')
  [ "$tracks" -gt 0 ] || { echo "  $name: no audio, skipping"; return 0; }

  echo "  importing '$name' ($tracks tracks) -> station $slug"
  # into the container's music volume, under inbox/<name>
  docker exec "$BRAIN" mkdir -p "/music/inbox" 2>/dev/null
  docker cp "$dir" "$BRAIN:/music/inbox/$name" 2>/dev/null || { echo "  copy failed"; return 1; }

  # create the station (library channel). Reuses jam-station's own channel machinery, so the
  # station behaves exactly like the CD/library ones — self-reloads onto the dial.
  docker exec -e SLUG="$slug" -e NAME="$name" "$BRAIN" python -c '
import os
from app import channels
slug, name = os.environ["SLUG"], os.environ["NAME"]
channels.create_channel(slug, name, f"Contributed: {name}", "library",
                        {"folders": [f"inbox/{name}"]})
print("  station created:", slug)
' 2>/dev/null || { echo "  station create failed"; return 1; }

  echo "$slug" >> "$LEDGER"
  echo "  ON AIR: $name"
}

scan_once() {
  for dir in "$INBOX"/*/; do
    [ -d "$dir" ] || continue
    dir="${dir%/}"
    s1=$(dir_size "$dir"); sleep 3; s2=$(dir_size "$dir")
    [ "$s1" = "$s2" ] || { echo "  $(basename "$dir"): still arriving, wait"; continue; }   # settle
    import_folder "$dir"
  done
}

if [ "${1:-}" = "--once" ]; then scan_once; exit 0; fi
echo "jam-inbox watching $INBOX every ${INTERVAL}s -> stations on $BRAIN"
while true; do scan_once; sleep "$INTERVAL"; done
