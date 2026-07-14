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
#   rip-cd.sh                                  # infer everything, ask before it rips
#   rip-cd.sh -a "Strength in Numbers" -A "The Telluride Sessions"
#   rip-cd.sh -y                               # don't ask
set -euo pipefail

ARTIST=""; ALBUM=""; YES=0
while getopts "a:A:y" o; do case $o in
  a) ARTIST=$OPTARG;; A) ALBUM=$OPTARG;; y) YES=1;;
esac; done

BRAIN=${BRAIN:-slab-jam-brain}
API=${API:-http://jam-brain.localhost:8080}
BITRATE=${BITRATE:-256}          # kbps, plain number: lame wants 256, ffmpeg wants 256k

disc=$(ls -d /Volumes/*/ 2>/dev/null | while read -r v; do
         compgen -G "$v*.aiff" >/dev/null && echo "$v" && break; done)
[ -n "${disc:-}" ] || { echo "no audio CD mounted. insert one and wait for the Finder to see it."; exit 1; }

# "3 After The Storm.aiff" -> track 3, title "After The Storm"
[ -n "$ALBUM" ]  || { ALBUM=$(basename "$disc"); [ "$ALBUM" = "Audio CD" ] && ALBUM=""; }
[ -n "$ALBUM" ]  || { read -rp "album name: " ALBUM; }
[ -n "$ARTIST" ] || { read -rp "artist: " ARTIST; }

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
DIR="$(safe "$ARTIST") - $(safe "$ALBUM")"
n=$(ls "$disc"*.aiff | wc -l | tr -d ' ')

echo "  disc    $disc"
echo "  ripping $n tracks -> music/cds/$DIR  @ ${BITRATE}k"
[ "$YES" = 1 ] || { read -rp "go? [y/N] " r; [ "$r" = y ] || exit 1; }

stage=$(mktemp -d); trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/$DIR"
i=0
for f in "$disc"*.aiff; do
  base=$(basename "$f" .aiff)
  num=${base%% *}; title=${base#* }
  [[ "$num" =~ ^[0-9]+$ ]] || { num=$((i+1)); title=$base; }
  i=$((i+1))
  out=$(printf '%02d %s.mp3' "$num" "$(safe "$title")")
  printf '  [%2d/%2d] %s\n' "$i" "$n" "$title"
  encode "$f" "$stage/$DIR/$out" "$title" "$num" "$n"
done

# The volume is inside Docker Desktop's VM — there is no host path to write to. docker cp is
# the door. mkdir first: cp needs the parent to exist.
docker exec "$BRAIN" mkdir -p /music/cds
docker cp "$stage/$DIR" "$BRAIN:/music/cds/$DIR"

slug=$(echo "$ALBUM" | tr "[:upper:]" "[:lower:]" | sed "s/[^a-z0-9]/-/g; s/--*/-/g; s/^-//; s/-$//" | cut -c1-30)
echo
echo "  ripped. now on the library disk as cds/$DIR"
echo "  give it a station:"
echo "    curl -s -X POST $API/api/channels -H 'content-type: application/json' \\"
echo "      -d '{\"slug\":\"$slug\",\"name\":\"$(safe "$ALBUM")\",\"source\":\"library\",\"query\":{\"folders\":[\"cds/$DIR\"]}}'"
echo "  (or add it to any existing library station's folders)"
