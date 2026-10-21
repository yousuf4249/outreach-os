#!/usr/bin/env bash
set -euo pipefail

# Directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

BACKUP_DIR="$ROOT_DIR/backups"
mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/weblinx_outreach_backup_${TIMESTAMP}.sql.gz"

# Source environment if present
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs -d '\n' 2>/dev/null || true)
fi

DB_USER="${POSTGRES_USER:-weblinx}"
DB_NAME="${POSTGRES_DB:-weblinx_outreach}"

echo "[*] Creating database backup for ${DB_NAME}..."

COMPOSE_CMD="docker compose"
if ! docker compose version &> /dev/null && command -v docker-compose &> /dev/null; then
  COMPOSE_CMD="docker-compose"
fi

$COMPOSE_CMD exec -T db pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"

echo "[✓] Backup completed successfully: $BACKUP_FILE"
echo "    Size: $(du -h "$BACKUP_FILE" | cut -f1)"

# Retain backups for 30 days
find "$BACKUP_DIR" -name "weblinx_outreach_backup_*.sql.gz" -type f -mtime +30 -delete
echo "[*] Rotated backups older than 30 days."
