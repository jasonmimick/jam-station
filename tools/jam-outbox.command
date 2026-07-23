#!/bin/bash
# jam-outbox — drag a folder in, it becomes a station.
#
# Generation 2 (2026-07-22): uses a PERSONAL upload token (see AGENTS.md's
# contributor-path section, docs/DESIGN-contributor-identity.md), not a
# shared SSH key. This file is still hand-delivered directly to ONE
# contributor (never posted anywhere public), so baking in THEIR OWN
# personal, individually-revocable token is exactly the intended shape --
# revoking it later never touches anyone else's access. Mint one with:
#   POST /api/contribute/token while signed in as that contributor
# and paste the raw token below before zipping this file up and sending it.
TOKEN="PASTE_THEIR_PERSONAL_TOKEN_HERE"
STATION="https://jam-station.runslab.run"

cd "$(dirname "$0")"

echo ""
echo "  SEND MUSIC TO THE FAMILY RADIO"
echo "  ------------------------------"
echo "  Drag your music folder into this window, then press Enter:"
echo ""
read -r folder

# Dragging a folder into Terminal often wraps it in quotes and escapes spaces
# with a backslash -- clean both up so the path underneath works either way.
folder="${folder%\"}"; folder="${folder#\"}"
folder="${folder//\\ / }"

if [ ! -d "$folder" ]; then
  echo ""
  echo "  Hmm, that doesn't look like a folder: $folder"
  echo "  Try again -- drag the folder itself (not a file inside it)."
  read -p "  Press Enter to close..."
  exit 1
fi

name=$(basename "$folder")
echo ""
echo "  Zipping \"$name\"..."
zip_path=$(mktemp -t jam-outbox).zip
# Zip the CONTENTS, not the folder itself -- the server extracts straight
# into its own inbox/<folder-name>/, matching Session's Send Music exactly.
( cd "$folder" && zip -r -q "$zip_path" . )

echo "  Sending..."
response=$(curl -s -w "\n%{http_code}" -X POST "$STATION/api/contribute" \
  -H "Authorization: Bearer $TOKEN" \
  -F "folder=$name" \
  -F "file=@$zip_path;type=application/zip")
rm -f "$zip_path"

http_code=$(echo "$response" | tail -1)
body=$(echo "$response" | sed '$d')

echo ""
if [ "$http_code" = "200" ]; then
  echo "  Done! Within a minute, \"$name\" will show up as its own station on the radio."
else
  echo "  Something went wrong (server said: $body)"
  echo "  Try again, or let Jason know if it keeps happening."
fi
echo ""
read -p "  Press Enter to close this window..."
