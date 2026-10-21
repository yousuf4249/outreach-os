#!/usr/bin/env bash
set -euo pipefail

echo "=========================================================="
echo "  Weblinx Outreach OS - Deployment Script"
echo "  Company: Weblinx Solution (https://weblinxsolution.com)"
echo "  Target:  https://outreach.weblinxsolution.com"
echo "=========================================================="

# Check for .env
if [ ! -f .env ]; then
  echo "[-] ERROR: .env file not found."
  echo "[*] Please copy .env.production.example to .env and configure secrets first:"
  echo "    cp .env.production.example .env"
  exit 1
fi

# Ensure docker & docker-compose are available
if ! command -v docker &> /dev/null; then
  echo "[-] ERROR: Docker is not installed. Please install Docker first."
  exit 1
fi

COMPOSE_CMD="docker compose"
if ! docker compose version &> /dev/null; then
  if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
  else
    echo "[-] ERROR: docker compose is not installed."
    exit 1
  fi
fi

# Create required directories
mkdir -p backups caddy_data caddy_config

echo "[+] Building and launching Weblinx Outreach OS containers..."
$COMPOSE_CMD pull --ignore-pull-failures db caddy || true
$COMPOSE_CMD build --pull app
$COMPOSE_CMD up -d --remove-orphans

echo "[+] Waiting for database and services to report healthy..."
for i in {1..30}; do
  DB_STATUS=$($COMPOSE_CMD ps --format json db 2>/dev/null | grep -o '"Health":"healthy"' || true)
  if [ -n "$DB_STATUS" ]; then
    echo "[✓] PostgreSQL database is healthy."
    break
  fi
  sleep 2
done

echo ""
echo "=========================================================="
echo "  [✓] Deployment complete!"
echo "  Application URL: https://outreach.weblinxsolution.com"
echo "  Check container status with: $COMPOSE_CMD ps"
echo "  View live logs with:         $COMPOSE_CMD logs -f"
echo "=========================================================="
