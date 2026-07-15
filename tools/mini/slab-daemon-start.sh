#!/bin/bash
# launchd runs this at login and keeps it alive; it is the slab daemon's supervisor-of-record
# on the mini. The daemon is useless without docker, and after a reboot docker is NOT up yet —
# so this guarantees Docker Desktop is running before handing off, then exec's the daemon so
# launchd watches the real process (this script's PID becomes the daemon's).
export PATH=/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin

open -ga Docker 2>/dev/null || true          # -g: don't steal focus if Jason's using the mac
for _ in $(seq 1 120); do                    # up to 6 min for the VM to come up after a reboot
  docker info >/dev/null 2>&1 && break
  sleep 3
done

exec /Users/jason/slab-go daemon
