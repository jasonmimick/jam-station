#!/bin/bash
# Restart jam-radio (liquidsoap) when it stops feeding icecast. Slab restarts a container
# only when it EXITS, and liquidsoap has hung twice without exiting (2026-10-04: alive but
# silent for 3 days, no icecast mounts; 2026-10-13: clock lagging 17s+ and growing).
# Run every 2 min by launchd (run.jam.radiowatch). A problem must show on two consecutive
# runs before we act, so the ~30s restart liquidsoap does itself after a channel toggle
# doesn't trigger a second one. At most one restart per 10 min.
#
#   radio-watch.sh            # check, restart if broken twice in a row
#   radio-watch.sh --dry-run  # print what it sees, change nothing
set -uo pipefail
export PATH="$PATH:/usr/local/bin:/opt/homebrew/bin"

ICECAST=${ICECAST_URL:-http://jam-icecast.localhost:8080}
CHANNELS=${CHANNELS_URL:-http://jam-listen.localhost:8080/api/channels}
CONTAINER=${RADIO_CONTAINER:-slab-jam-radio}
STATE=${STATE_DIR:-$HOME/.jam-radiowatch}
LAG_LIMIT=${LAG_LIMIT:-60}        # seconds behind real time
mkdir -p "$STATE"
log() { echo "$(date '+%F %T') $*"; }

# Mounts icecast has a live source on, vs. playable channels that should have one. Library
# "shelf-*" channels are excluded: the music isn't mounted on slab, so they never get mounts.
sources=$(curl -s -m 25 "$ICECAST/status-json.xsl" | python3 -c '
import sys, json
s = json.load(sys.stdin)["icestats"].get("source", [])
print(len(s) if isinstance(s, list) else 1)' 2>/dev/null || echo "")
want=$(curl -s -m 25 "$CHANNELS" | python3 -c '
import sys, json
print(sum(1 for c in json.load(sys.stdin) if c.get("playable") and c.get("source") != "library"))' 2>/dev/null || echo "")

# Worst "We must catchup N seconds" in the last 2 min.
lag=$(docker logs --since 2m "$CONTAINER" 2>&1 | sed -n 's/.*We must catchup \([0-9]*\)\..*/\1/p' | sort -n | tail -1)
lag=${lag:-0}

problem=""
if [ -z "$sources" ] || [ -z "$want" ]; then
  log "can't read icecast/channels (sources='$sources' want='$want') — skipping, not blaming the radio"
  exit 0
elif [ "$sources" -lt "$want" ]; then problem="icecast has $sources mounts, expected >= $want"
elif [ "$lag" -ge "$LAG_LIMIT" ]; then problem="clock ${lag}s behind"
fi

if [ "${1:-}" = "--dry-run" ]; then log "sources=$sources want=$want lag=${lag}s problem='${problem:-none}'"; exit 0; fi

if [ -z "$problem" ]; then rm -f "$STATE/strike"; exit 0; fi
if [ ! -f "$STATE/strike" ]; then touch "$STATE/strike"; log "strike 1: $problem"; exit 0; fi

last=$(cat "$STATE/last-restart" 2>/dev/null || echo 0)
if [ $(( $(date +%s) - last )) -lt 600 ]; then log "strike 2 ($problem) but restarted <10 min ago — waiting"; exit 0; fi

log "strike 2: $problem — restarting $CONTAINER"
docker exec "$CONTAINER" sh -c 'find /tmp -maxdepth 1 -name "liq-*" -delete' 2>/dev/null
docker restart "$CONTAINER" >/dev/null && date +%s > "$STATE/last-restart"
rm -f "$STATE/strike"
