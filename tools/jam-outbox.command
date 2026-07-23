#!/bin/bash
# jam-outbox — the contributor's half of jam-inbox.sh. Drag a folder in, it
# becomes a station. Ships alongside its own dedicated, restricted key
# (dad_key, gitignored — generate ONE per contributor, never commit it, never
# reuse the owner's own key) so the contributor never runs ssh-keygen
# themselves. Zip this file + its dad_key together and send the whole thing.
cd "$(dirname "$0")"
chmod 600 dad_key 2>/dev/null

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
echo "  Sending \"$name\"..."
echo ""

# Make sure the files are actually readable by whoever picks them up on the
# other end -- a real contributor's files showed up owner-only-readable
# (wherever he originally got them), which the mini's import job (a DIFFERENT
# account) couldn't read at all. openrsync's --chmod/--no-perms don't reliably
# override this (tested), so fix it at the source instead: the contributor
# always owns their own files, so relaxing permissions here always succeeds
# regardless of how restrictive they started.
chmod -R go+rX "$folder" 2>/dev/null

rsync -av -e "ssh -i ./dad_key -o StrictHostKeyChecking=accept-new" "$folder" mark@jasons-mac-mini:jam-inbox/

echo ""
echo "  Done! Within a minute, \"$name\" will show up as its own station on the radio."
echo ""
read -p "  Press Enter to close this window..."
