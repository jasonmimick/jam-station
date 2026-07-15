#!/bin/bash
# Pull jam-station's postgres dumps OFF the mini onto this machine (euler) — the off-site copy.
# The mini makes daily local dumps; this drags them somewhere else, so the mini's disk dying
# doesn't take the only backups with it. euler->mini is the reachable direction (tailscale +
# id_euler), so euler PULLS; the mini never has to know euler exists.
#
# Runs on euler. Schedule via tools/euler/run.jam.pullbackups.plist, or just run it by hand.
set -euo pipefail

MINI=${MINI:-jason@jasons-mac-mini}
KEY=${KEY:-$HOME/.ssh/id_euler}
DEST=${DEST:-$HOME/jam-backups/mini}
KEEP=${KEEP:-30}                       # keep MORE off-site than the mini's 14 — that's the point
SSH="ssh -o IdentitiesOnly=yes -o ConnectTimeout=15 -i $KEY"
mkdir -p "$DEST"

# rsync if we have it (only moves new/changed), else scp the lot. No --delete: off-site should
# outlive what the mini has rotated away.
if command -v rsync >/dev/null; then
  rsync -az -e "$SSH" "$MINI:jam-backups/" "$DEST/" 2>/dev/null \
    || { echo "rsync failed — is the mini reachable?"; exit 1; }
else
  scp -q -o IdentitiesOnly=yes -o ConnectTimeout=15 -i "$KEY" \
    "$MINI:jam-backups/jam-*.sql.gz" "$DEST/" 2>/dev/null \
    || { echo "scp failed — is the mini reachable?"; exit 1; }
fi

n=$(ls -1 "$DEST"/jam-*.sql.gz 2>/dev/null | wc -l | tr -d ' ')
newest=$(ls -1t "$DEST"/jam-*.sql.gz 2>/dev/null | head -1)
echo "off-site: $n dump(s) in $DEST (newest: $(basename "${newest:-none}"))"
ls -1t "$DEST"/jam-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
