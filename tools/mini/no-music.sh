#!/bin/bash
# Keep Apple Music from running on the ripping server. Music auto-launches when a CD is inserted
# and grabs/ejects the disc before our watcher can rip it — and the supported way to stop that
# (the digihub "ignore" preference) simply doesn't work on macOS 26. This is the blunt but
# reliable answer: a headless media server has no reason to run Music, so quit it on sight.
# Every 3s is plenty — Music can't do anything with a disc in that window.
while true; do
  pkill -x Music 2>/dev/null
  sleep 3
done
