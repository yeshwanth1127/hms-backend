#!/bin/bash
# Nightly backup: Postgres (custom format) + uploaded media, kept for KEEP_DAYS.
# Cron (as the app user):  15 2 * * *  /var/www/hms-backend/deploy/backup.sh >> /var/log/hms-backup.log 2>&1
# Restore steps: deploy/RESTORE.md
set -euo pipefail
APP_DIR=${APP_DIR:-/var/www/hms-backend}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/hms}
KEEP_DAYS=${KEEP_DAYS:-14}

# Read only the two settings needed; never `source` the whole .env.
setting() { grep -E "^$1=" "$APP_DIR/.env" | tail -1 | cut -d= -f2-; }
DATABASE_URL=${DATABASE_URL:-$(setting DATABASE_URL)}
MEDIA_DIR=${MEDIA_DIR:-$(setting MEDIA_DIR)}
MEDIA_DIR=${MEDIA_DIR:-./uploads}
[[ $MEDIA_DIR = /* ]] || MEDIA_DIR="$APP_DIR/${MEDIA_DIR#./}"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BACKUP_DIR"
umask 077                                   # patient data: owner-only files
pg_dump --format=custom --no-owner --dbname="${DATABASE_URL/+psycopg/}" --file="$BACKUP_DIR/db-$stamp.dump.partial"
pg_restore --list "$BACKUP_DIR/db-$stamp.dump.partial" > /dev/null   # fail now, not on restore day
mv "$BACKUP_DIR/db-$stamp.dump.partial" "$BACKUP_DIR/db-$stamp.dump"
if [ -d "$MEDIA_DIR" ]; then
  tar -czf "$BACKUP_DIR/media-$stamp.tar.gz" -C "$MEDIA_DIR" .
fi
find "$BACKUP_DIR" -maxdepth 1 \( -name 'db-*.dump' -o -name 'media-*.tar.gz' \) -mtime +"$KEEP_DAYS" -delete
echo "$(date -u +%FT%TZ) backup ok: db-$stamp.dump"
# ponytail: same-machine copies only; add an off-site sync (rclone/S3) — a dead disk takes both.
