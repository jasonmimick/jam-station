#!/bin/bash
# Make the station survive a reboot. Installs three launchd agents on the mini —
#   run.slab.daemon   the slab daemon (waits for Docker first)
#   run.slab.tunnel   the cloudflared tunnel to jam-station.runslab.run
#   run.jam.cdwatch   the CD auto-ingest watcher
# — and cuts over from the nohup orphans currently running. Idempotent: safe to re-run.
#
#   ssh mini 'bash ~/business/jam-station/tools/mini/install.sh'
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
LA=~/Library/LaunchAgents
DOM="gui/$(id -u)"
mkdir -p "$LA" ~/bin ~/Library/Logs

install -m 755 "$HERE/slab-daemon-start.sh" ~/bin/slab-daemon-start.sh

swap() {   # label  -- retire the nohup orphan, then hand the job to launchd
  local label=$1 pattern=$2
  cp "$HERE/$label.plist" "$LA/$label.plist"
  launchctl bootout "$DOM/$label" 2>/dev/null || true   # unload a previous version if any
  if [ -n "$pattern" ]; then
    pkill -f "$pattern" 2>/dev/null || true              # kill the un-managed process
    sleep 1
  fi
  launchctl bootstrap "$DOM" "$LA/$label.plist"
  launchctl enable "$DOM/$label"
  echo "  loaded $label"
}

# the CD-watch helper that holds Full Disk Access (see jam-cdd.c) — build it before its agent
clang -O2 -o ~/bin/jam-cdd "$HERE/jam-cdd.c" && echo "  built ~/bin/jam-cdd"

# ── keep the GUI session fully live for ripping ──────────────────────────────
# caffeinate (run.jam.awake) stops SLEEP but NOT the screensaver — and the screensaver engaging
# is what makes a rip "get funky when the screen locks." Disable it outright (idleTime 0), never
# ask for a password on this headless rig, and keep the optical drive from spinning down mid-rip.
defaults -currentHost write com.apple.screensaver idleTime -int 0
defaults -currentHost write com.apple.screensaver askForPassword -int 0
pmset -a disksleep 0 2>/dev/null || sudo pmset -a disksleep 0 2>/dev/null || true
killall cfprefsd 2>/dev/null || true
echo "  session hardened: screensaver off, no lock, disk stays awake"

swap run.slab.daemon "slab-go daemon"
swap run.slab.tunnel "cloudflared tunnel run"
swap run.jam.cdwatch ""            # nothing was running before; just load it
swap run.jam.backup ""             # daily postgres backup (members + access keys)
swap run.jam.awake "caffeinate -dis"  # keep display awake so discs mount on the headless mini
swap run.jam.nomusic "no-music.sh"      # Apple Music hijacks + ejects discs; keep it dead

echo "done. launchctl list | grep -E 'slab|jam' to see them."
