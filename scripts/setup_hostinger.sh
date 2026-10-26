#!/usr/bin/env bash
# ==============================================================================
# Weblinx Outreach OS – Hostinger VPS Automated Setup Script
# Run this once on a fresh Ubuntu 22.04 / 24.04 Hostinger VPS
# Usage:
#   chmod +x scripts/setup_hostinger.sh
#   ./scripts/setup_hostinger.sh
# ==============================================================================
set -euo pipefail

echo "=========================================================="
echo "  Weblinx Outreach OS – Automated Hostinger VPS Setup"
echo "=========================================================="

# 1. Update system packages
echo "[1/5] Updating system packages..."
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y git curl wget ufw ca-certificates gnupg openssl

# 2. Configure Firewall (UFW)
echo "[2/5] Configuring firewall rules (SSH, HTTP, HTTPS)..."
sudo ufw allow 22/tcp || true
sudo ufw allow 80/tcp || true
sudo ufw allow 443/tcp || true
sudo ufw --force enable || true

# 3. Install Docker & Docker Compose Plugin (Official Docker Repo)
echo "[3/5] Installing Docker & Docker Compose..."
if ! command -v docker &> /dev/null; then
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=\"$(dpkg --print-architecture)\" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      \"$(. /etc/os-release && echo \"$VERSION_CODENAME\")\" stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo systemctl enable docker
    sudo systemctl start docker
    echo "[✓] Docker installed successfully."
else
    echo "[✓] Docker is already installed."
fi

# 4. Prepare Environment Configuration (.env)
echo "[4/5] Checking environment configuration..."
if [ ! -f .env ]; then
    if [ -f .env.production.example ]; then
        cp .env.production.example .env
        RANDOM_KEY=$(openssl rand -hex 32)
        # Replace placeholder JWT key with secure random secret
        sed -i "s/change_me_to_a_long_random_64_character_hex_secret_string/${RANDOM_KEY}/g" .env
        echo "[✓] Generated .env from .env.production.example with secure random JWT_SECRET_KEY."
        echo "[!] Make sure to verify CADDY_HOST, BASE_URL, and OAuth credentials in .env if needed."
    else
        echo "[!] Warning: .env.production.example not found. Please create .env manually."
    fi
else
    echo "[✓] .env already exists."
fi

# 5. Run Automated Build & Deploy
echo "[5/5] Launching containers via deploy.sh..."
chmod +x scripts/*.sh
./scripts/deploy.sh

echo ""
echo "=========================================================="
echo "  [✓] Setup & Deployment Complete!"
echo "  Verify running containers with: docker compose ps"
echo "  View live logs with:            docker compose logs -f"
echo "=========================================================="
