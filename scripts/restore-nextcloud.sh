#!/usr/bin/env bash
# Restore Nextcloud (db + data + config) from the encrypted backup made by
# backup-nextcloud.sh. Run on the target host with the NC containers already up:
#   sudo bash restore-nextcloud.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# .env lives at repo root; this script may sit at root or under scripts/
if   [[ -f "$SCRIPT_DIR/.env" ]];    then ENV_FILE="$SCRIPT_DIR/.env"
elif [[ -f "$SCRIPT_DIR/../.env" ]]; then ENV_FILE="$SCRIPT_DIR/../.env"
else echo "cannot find .env near $SCRIPT_DIR" >&2; exit 1; fi
set -a; source "$ENV_FILE"; set +a

NC_VOLUME="/var/lib/docker/volumes/stack_nextcloud-data/_data"
BACKUP_ZIP="${1:-$MEMORY_DIR/nextcloud-backup.7z}"
STAGING_DIR="$(mktemp -d)"
log() { echo "[restore] $*"; }

[[ -f "$BACKUP_ZIP" ]] || { echo "no backup at $BACKUP_ZIP" >&2; exit 1; }
cleanup() { rm -rf "$STAGING_DIR"; }
trap cleanup EXIT

log "Extracting $BACKUP_ZIP ..."
7z x -p"${NEXTCLOUD_ADMIN_PASSWORD}" -o"$STAGING_DIR" "$BACKUP_ZIP" >/dev/null

# backup stored absolute staging paths, so locate the pieces wherever they landed
SQL="$(find "$STAGING_DIR" -name nextcloud-db.sql | head -1)"
[[ -n "$SQL" ]] || { echo "nextcloud-db.sql not found in archive" >&2; exit 1; }
BASE="$(dirname "$SQL")"
[[ -d "$BASE/data" && -d "$BASE/config" ]] || { echo "data/ or config/ missing in archive" >&2; exit 1; }
log "Found: $SQL  +  $BASE/{data,config}"

log "Maintenance mode ON"
docker exec -u www-data nextcloud php /var/www/html/occ maintenance:mode --on

log "Importing database (drops+recreates nextcloud tables)..."
docker exec -i nextcloud-db mysql -u nextcloud -p"${NEXTCLOUD_DB_PASSWORD}" nextcloud < "$SQL"

log "Restoring data/ + config/ through the container (no host root needed)..."
docker exec nextcloud rm -rf /var/www/html/data /var/www/html/config
tar -C "$BASE" -cf - data config | docker exec -i nextcloud tar -C /var/www/html -xf -

log "Fixing ownership..."
docker exec nextcloud chown -R www-data:www-data /var/www/html/data /var/www/html/config

log "Maintenance mode OFF"
docker exec -u www-data nextcloud php /var/www/html/occ maintenance:mode --off

log "Rescanning files + repairing indices..."
docker exec -u www-data nextcloud php /var/www/html/occ files:scan --all || true
docker exec -u www-data nextcloud php /var/www/html/occ db:add-missing-indices || true

log "Done. Verify login at nextcloud.kacper.me (or http://localhost:8090)."
