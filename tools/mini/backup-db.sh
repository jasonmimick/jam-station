#!/bin/bash
# Back up jam-station's postgres — the crown jewels now that members + access_keys live in it.
# Everything else (channels, queue, nowplaying) reseeds itself from code; the ONE thing that
# can't be regenerated is who has access. Lose that table and every person is locked out.
#
#   backup-db.sh                 # dump + rotate (what launchd runs daily)
#   backup-db.sh restore <file>  # restore a dump (OVERWRITES current data)
#   backup-db.sh list            # show what's on hand
set -euo pipefail

DIR=${JAM_BACKUP_DIR:-$HOME/jam-backups}
KEEP=${KEEP:-14}
PGC=${PGC:-slab-postgres}
# The per-app db is slab_<name> (hyphens->underscores). Auto-detect so a rename can't silently
# back up nothing; fall back to the known name.
DB=${JAM_DB:-$(docker exec "$PGC" psql -U slab -Atc \
   "SELECT datname FROM pg_database WHERE datname LIKE 'slab_jam%' ORDER BY datname LIMIT 1" \
   2>/dev/null || true)}
DB=${DB:-slab_jam_brain}
mkdir -p "$DIR"

case "${1:-backup}" in
  backup)
    ts=$(date +%Y%m%d-%H%M%S)
    out="$DIR/jam-$ts.sql.gz"
    # --clean --if-exists so the dump restores cleanly OVER an existing db (drop then recreate),
    # which is what disaster recovery actually needs.
    docker exec "$PGC" pg_dump -U slab --clean --if-exists "$DB" | gzip > "$out"
    # A backup you can't trust is worse than none — verify it's a valid gzip that actually
    # contains our schema before we count it and rotate old ones away.
    if ! gzip -t "$out" 2>/dev/null || [ "$(gzip -dc "$out" | grep -c 'CREATE TABLE')" -lt 1 ]; then
      echo "backup looks broken — keeping old ones, removing this"; rm -f "$out"; exit 1
    fi
    echo "backed up $DB -> $out ($(du -h "$out" | cut -f1))"
    ls -1t "$DIR"/jam-*.sql.gz 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
    ;;
  restore)
    f=${2:?usage: backup-db.sh restore <file.sql.gz>}
    [ -f "$f" ] || { echo "no such file: $f"; exit 1; }
    echo "restoring $f into $DB — this OVERWRITES current data. Ctrl-C in 5s to abort."; sleep 5
    gzip -dc "$f" | docker exec -i "$PGC" psql -U slab -v ON_ERROR_STOP=1 "$DB"
    echo "restored."
    ;;
  list)
    ls -lht "$DIR"/jam-*.sql.gz 2>/dev/null || echo "no backups yet in $DIR"
    ;;
  *) echo "usage: backup-db.sh [backup|restore <file>|list]"; exit 2;;
esac
