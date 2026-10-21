#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <path_to_backup_file.sql.gz>"
  exit 1
fi

BACKUP_FILE="$1"
if [ ! -f "$BACKUP_FILE" ]; then
  echo "[-] ERROR: File $BACKUP_FILE does not exist."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs -d '\n' 2>/dev/null || true)
fi

DB_USER="${POSTGRES_USER:-weblinx}"
DB_NAME="${POSTGRES_DB:-weblinx_outreach}"

echo "=========================================================="
echo "  WARNING: Database Restore"
echo "  Target Database: $DB_NAME"
echo "  Backup Source:   $BACKUP_FILE"
echo "  This will overwrite existing database records!"
echo "=========================================================="
read -p "Are you sure you want to proceed? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Restore cancelled."
  exit 0
fi

COMPOSE_CMD="docker compose"
if ! docker compose version &> /dev/null && command -v docker-compose &> /dev/null; then
  COMPOSE_CMD="docker-compose"
fi

echo "[*] Restoring database from $BACKUP_FILE..."
gunzip -c "$BACKUP_FILE" | $COMPOSE_CMD exec -T db psql -U "$DB_USER" "$DB_NAME"

echo "[✓] Database restored successfully."
echo "[*] Restarting application service..."
$COMPOSE_CMD restart app
echo "[✓] App restarted."
