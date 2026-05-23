#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load env vars (MEMORY_DIR, NEXTCLOUD_DB_PASSWORD, NEXTCLOUD_ADMIN_PASSWORD)
set -a
source "$SCRIPT_DIR/.env"
set +a

NC_VOLUME="/var/lib/docker/volumes/stack_nextcloud-data/_data"
STAGING_DIR="$(mktemp -d)"
OUTPUT_ZIP="$MEMORY_DIR/nextcloud-backup.7z"
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

log() { echo "[$TIMESTAMP] $*"; }

cleanup() {
    log "Disabling Nextcloud maintenance mode..."
    docker exec -u www-data nextcloud php /var/www/html/occ maintenance:mode --off
    rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

log "Enabling Nextcloud maintenance mode..."
docker exec -u www-data nextcloud php /var/www/html/occ maintenance:mode --on

log "Dumping database..."
docker exec nextcloud-db mysqldump \
    -u nextcloud \
    -p"${NEXTCLOUD_DB_PASSWORD}" \
    --single-transaction \
    nextcloud > "$STAGING_DIR/nextcloud-db.sql"

log "Copying data directory..."
rsync -a "$NC_VOLUME/data/" "$STAGING_DIR/data/"

log "Copying config directory..."
rsync -a "$NC_VOLUME/config/" "$STAGING_DIR/config/"

log "Creating encrypted zip..."
rm -f "$OUTPUT_ZIP"
7z a -mhe=on -p"${NEXTCLOUD_ADMIN_PASSWORD}" "$OUTPUT_ZIP" "$STAGING_DIR/"* > /dev/null

log "Backup complete -> $OUTPUT_ZIP"
