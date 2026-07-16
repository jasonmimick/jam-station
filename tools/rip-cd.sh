#!/usr/bin/env bash
# Rip the CD in the drive into jam-station's record library.
#
# WHY THIS RUNS ON THE HOST AND NOT IN THE APP:
# the brain is a container, and slab deliberately forbids host mounts (named volumes only).
# So no app can ever see /dev/disk6 or /Volumes/Audio CD. That's not a slab bug to route
# around — a PaaS that lets any app grab the host's hardware isn't a PaaS. The disc lives on
# the host, so the ripper lives on the host, and it hands the finished MP3s to the app the
# same way you'd hand it any other file: over docker.
#
# macOS does the hard part for free: it mounts an audio CD as AIFF files, ALREADY NAMED from
# its metadata lookup ("1 The West County.aiff"). So there is no cdparanoia, no CDDB client,
# and no disc-id maths here — just a transcode. If the disc is unknown, the tracks come out
# as "1 Audio Track.aiff" and you pass -a/-A to name them yourself.
#
#   rip-cd.sh                                  # first audio CD found; identify via MusicBrainz
#   rip-cd.sh -d "/Volumes/Some CD/"           # a SPECIFIC drive's disc (the watcher uses this)
#   rip-cd.sh -a "Strength in Numbers" -A "The Telluride Sessions"   # name it yourself
#   rip-cd.sh -y -e                            # unattended: don't ask, eject when done
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ARTIST=""; ALBUM=""; YES=0; EJECT=0; DISC_ARG=""
while getopts "a:A:yed:" o; do case $o in
  a) ARTIST=$OPTARG;; A) ALBUM=$OPTARG;; y) YES=1;; e) EJECT=1;; d) DISC_ARG=$OPTARG;;
esac; done

BRAIN=${BRAIN:-slab-jam-brain}
API=${API:-http://jam-brain.localhost:8080}
BITRATE=${BITRATE:-256}          # kbps, plain number: lame wants 256, ffmpeg wants 256k
LEDGER=${LEDGER:-$HOME/.jam-ripped}

# Does this dir hold .aiff tracks? Glob a QUOTED dir so brackets in the volume name (e.g.
# "Sampler [Disc 1]") stay literal — `compgen -G` re-globs its whole argument and reads the
# [..] as a character class, so it never matches a bracketed disc. This idiom is bracket-safe.
has_aiff() { local f; for f in "$1"*.aiff; do [ -e "$f" ] && return 0; done; return 1; }

# Which disc: a specific drive's volume if -d given (that's how the watcher points one ripper
# at one drive), else the first audio CD found (the convenient manual default).
if [ -n "$DISC_ARG" ]; then
  disc=$DISC_ARG
  has_aiff "$disc" || { echo "no audio CD at $disc"; exit 1; }
else
  disc=$(ls -d /Volumes/*/ 2>/dev/null | while read -r v; do
           has_aiff "$v" && echo "$v" && break; done)
fi
[ -n "${disc:-}" ] || { echo "no audio CD mounted. insert one and wait for the Finder to see it."; exit 1; }

# Clear the drive of everything else that reads it — the CD has ONE head, and a rival reader
# turns lame's read into a stall (the buzzing). macOS piles on when a disc mounts: Spotlight
# indexes it, QuickLook generates previews, Music imports — each reads the same tracks lame
# does. declutter() shoos them off; we call it before ripping AND every track (they relaunch).
declutter() {
  # each pkill returns non-zero when there's nothing to kill (the usual case), which under
  # `set -e` would kill the RIP — so every one must swallow its failure.
  pkill -x Music 2>/dev/null || true
  pkill -f quicklookd 2>/dev/null || true
  pkill -f QuickLookUIService 2>/dev/null || true
  pkill -f qlmanage 2>/dev/null || true
  return 0
}
mdutil -i off "$disc" >/dev/null 2>&1 || true   # Spotlight: skip this volume (best-effort; may need root)
declutter

# ONE RIPPER PER DRIVE, not per host. The constraint is physical: a drive has one head, so two
# rippers on the SAME drive fight it and both crawl — but two DIFFERENT drives are independent
# and should rip in parallel. So the lock is keyed on the drive device (via df), not global.
# mkdir is atomic — exactly one caller wins the lock for a given drive. Support whatever the
# host has: 0 drives, 1, or a stack of USB burners, each with its own ripper.
drive=$(df "$disc" 2>/dev/null | awk 'NR==2{print $1}' | sed 's#^/dev/##; s/s[0-9]*$//')
LOCK=${LOCK_DIR:-/tmp/jam-rip-${drive:-single}.lock}
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "  a ripper is already on drive ${drive:-?} (lock $LOCK) — skipping"; exit 3
fi
stage=""
trap 'rmdir "$LOCK" 2>/dev/null || true; [ -n "$stage" ] && rm -rf "$stage"' EXIT

# The disc's identity, for the ledger (so it is never re-ripped): its track list, hashed.
sig=$(ls -la "$disc"*.aiff 2>/dev/null | awk '{print $5, $NF}' | shasum | cut -d' ' -f1)

# Identify the disc from its physical TOC (MusicBrainz) — the only naming that works
# unattended, since macOS leaves album/artist blank. -a/-A always win over the lookup.
if [ -z "$ALBUM" ] || [ -z "$ARTIST" ]; then
  if id=$(python3 "$HERE/cd-name.py" 2>/dev/null) && [ -n "$id" ]; then
    [ -n "$ARTIST" ] || ARTIST=${id%%$'\t'*}
    [ -n "$ALBUM" ]  || ALBUM=${id#*$'\t'}
    echo "  identified: $ARTIST — $ALBUM"
  fi
fi
# Still nameless? A prompt if someone's watching; a dated folder if nobody is. NEVER a wrong
# name — an unidentified disc lands in the catalog as "Unknown" for one-click renaming later,
# titles intact, rather than masquerading as something it isn't.
if [ "$YES" = 0 ]; then
  [ -n "$ALBUM" ]  || { read -rp "album name: " ALBUM; }
  [ -n "$ARTIST" ] || { read -rp "artist: " ARTIST; }
fi
# MusicBrainz didn't know it? macOS often still named the VOLUME after the album (that's how
# "A Generation Ago Today" mounts). Use that before falling back to a meaningless dated folder
# — a real title beats "Unknown Album 2026-...". Only skip the generic mount names.
if [ -z "$ALBUM" ]; then
  vol=$(basename "$disc")
  case "$vol" in "Audio CD"|"Untitled"|"Untitled CD"|"") ;; *) ALBUM=$vol;; esac
fi
[ -n "$ALBUM" ]  || ALBUM="Unknown Album $(date +%Y-%m-%d-%H%M)"
[ -n "$ARTIST" ] || ARTIST="Unknown Artist"

# Strip what a path can't hold, and nothing else. An allowlist of [:alnum:] would quietly
# turn "Béla" into "Bla" and "Motörhead" into "Motrhead" — the accents are part of the name.
safe() { echo "$1" | sed 's#[/\\:*?"<>|]#-#g; s/  */ /g; s/^ *//; s/ *$//'; }

# LAME, NOT FFMPEG. The mini's ffmpeg is a broken x86 Homebrew build (a dangling
# libunistring dylib), and reaching for `brew reinstall` would be treating a 300MB
# dependency as load-bearing when it isn't: lame reads AIFF natively and IS the encoder
# ffmpeg was shelling out to (libmp3lame). One less thing that can rot. ffmpeg stays as a
# fallback for boxes that have it and not lame.
encode() {           # in out title track total
  if command -v lame >/dev/null; then
    lame --quiet -b "$BITRATE" --add-id3v2 \
      --tt "$3" --ta "$ARTIST" --tl "$ALBUM" --tn "$4/$5" "$1" "$2"
  elif command -v ffmpeg >/dev/null; then
    ffmpeg -loglevel error -y -i "$1" -vn -codec:a libmp3lame -b:a "${BITRATE}k" \
      -metadata title="$3" -metadata artist="$ARTIST" -metadata album="$ALBUM" \
      -metadata track="$4/$5" "$2"
  else
    echo "need lame (brew install lame) or ffmpeg" >&2; exit 1
  fi
}
# Tell the UI what's ripping. The ripper's on the host and can't call the brain's API, but it
# CAN drop a status file into the brain's music volume via docker. The UI reads /api/rip.
# python does the JSON escaping so brackets/quotes/accents in a title can't break it.
jstr() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1" 2>/dev/null || echo '""'; }
report() {   # state track total title
  printf '{"state":"%s","album":%s,"track":%s,"total":%s,"title":%s}' \
    "$1" "$(jstr "$ALBUM")" "${2:-0}" "${3:-0}" "$(jstr "${4:-}")" \
    | docker exec -i "$BRAIN" sh -c 'cat > /music/.rip-status' 2>/dev/null || true
}

DIR="$(safe "$ARTIST") - $(safe "$ALBUM")"
n=$(ls "$disc"*.aiff | wc -l | tr -d ' ')

echo "  disc    $disc"
echo "  ripping $n tracks -> music/cds/$DIR  @ ${BITRATE}k"
[ "$YES" = 1 ] || { read -rp "go? [y/N] " r; [ "$r" = y ] || exit 1; }

stage=$(mktemp -d)          # cleaned up by the EXIT trap set with the lock, above
mkdir -p "$stage/$DIR"
i=0; ok=0                   # ok = tracks that actually ripped (a damaged one gets skipped)
for f in "$disc"*.aiff; do
  base=$(basename "$f" .aiff)
  num=${base%% *}; title=${base#* }
  [[ "$num" =~ ^[0-9]+$ ]] || { num=$((i+1)); title=$base; }
  i=$((i+1))
  out=$(printf '%02d %s.mp3' "$num" "$(safe "$title")")
  printf '  [%2d/%2d] %s\n' "$i" "$n" "$title"
  report ripping "$i" "$n" "$title"
  declutter                          # QuickLook/Spotlight/Music relaunch — shoo them off again
  # A damaged/unreadable track must NOT kill the whole rip — skip it and keep going, so a
  # scratched disc still yields its other tracks instead of failing entirely (and looping).
  if encode "$f" "$stage/$DIR/$out" "$title" "$num" "$n"; then
    ok=$((ok + 1))
  else
    echo "  [!] track $num unreadable — skipped"
    rm -f "$stage/$DIR/$out"
  fi
done
[ "${ok:-0}" -gt 0 ] || { echo "  no readable tracks — clean the disc and try again"; exit 1; }

# The volume is inside Docker Desktop's VM — there is no host path to write to. docker cp is
# the door. mkdir first: cp needs the parent to exist.
docker exec "$BRAIN" mkdir -p /music/cds
docker cp "$stage/$DIR" "$BRAIN:/music/cds/$DIR"
report done "$n" "$n" ""       # UI shows "added <album>", then goes idle when this goes stale

# Ledger it now that the bytes are safely in the volume — the ripper records its OWN outcome,
# so the watcher never has to track a background job. A partial/failed rip exits before here
# and leaves the disc un-ledgered, so it gets retried. (Manual re-rips still work: only the
# watcher consults the ledger.)
[ -n "$sig" ] && echo "$sig  $(date '+%Y-%m-%d %H:%M')  $DIR" >> "$LEDGER"

# No per-CD channel. Every ripped album lands in ONE place — the cds/ catalog — browsable and
# on-demand, and the 'disc-changer' station shuffles them all. A station per disc would be a
# dial full of one-album channels; the catalog is the shelf.
echo
echo "  ripped -> catalog as cds/$DIR"
# Eject needs FORCE: the GUI login session (loginwindow) holds optical volumes, so a plain
# unmount over SSH gets dissented and the disc stays put. Force overrides it. Eject the device
# node, not the mount point, to sidestep any spaces-in-the-name quirks.
if [ "$EJECT" = 1 ]; then
  dev=$(diskutil info "$disc" 2>/dev/null | awk -F: '/Device Node/{gsub(/ /,"",$2);print $2}')
  diskutil eject force "${dev:-$disc}" >/dev/null 2>&1 || drutil eject >/dev/null 2>&1 || true
  echo "  ejected — next disc when you're ready"
fi
echo "  it's in the catalog now (members-only) and on The Disc Changer."
