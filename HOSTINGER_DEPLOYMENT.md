# Hostinger VPS Deployment Guide: Weblinx Outreach OS

**Application:** Weblinx Outreach OS  
**Organization:** Weblinx Solution ([weblinxsolution.com](https://weblinxsolution.com))  
**Target Domain:** [https://outreach.weblinxsolution.com](https://outreach.weblinxsolution.com)  

---

## 1. Architecture & Safe Server Isolation

Weblinx Outreach OS runs entirely inside isolated Docker containers (Application, PostgreSQL, and Caddy Reverse Proxy).

> [!IMPORTANT]
> **Complete Website Isolation:** If your main website `https://weblinxsolution.com` is hosted on a separate web hosting plan or VPS, this deployment will **NOT** interfere with it. It only listens for requests addressed specifically to the subdomain `outreach.weblinxsolution.com`.
> Even if running on the same Hostinger VPS alongside other services, it binds exclusively through Docker ports 80/443 without touching system-level web directories or existing databases.

---

## 2. DNS Configuration

Before deploying, configure your DNS in your domain registrar / DNS manager (Hostinger / Cloudflare):

| Type | Name / Host | Points to | TTL | Proxy Status |
| :--- | :--- | :--- | :--- | :--- |
| **A** | `outreach` | `<YOUR_HOSTINGER_VPS_IPV4>` | 300 / Auto | **DNS Only** (Grey Cloud if using Cloudflare) |

*(Note: If using Cloudflare, set the proxy status to "DNS Only" initially so Caddy can perform the Let's Encrypt HTTP-01 ACME challenge smoothly).*

---

## 3. Hostinger VPS Initial Setup

Connect to your Hostinger VPS via SSH:

```bash
ssh root@<YOUR_VPS_IP>
```

### 3.1. Update System Packages
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl wget ufw ca-certificates gnupg
```

### 3.2. Configure Firewall (UFW)
Allow SSH, HTTP, and HTTPS:
```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 3.3. Install Docker & Docker Compose
```bash
# Install Docker official repository
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Verify installation
docker --version
docker compose version
```

---

## 4. Deploying Weblinx Outreach OS

### 4.1. Clone Repository
Clone the codebase into `/opt/weblinx-outreach`:

```bash
sudo mkdir -p /opt/weblinx-outreach
sudo chown $USER:$USER /opt/weblinx-outreach
git clone -b weblinx-main <YOUR_GIT_REPO_URL> /opt/weblinx-outreach
cd /opt/weblinx-outreach
```

### 4.2. Configure Environment Variables
Copy the production template to `.env`:

```bash
cp .env.production.example .env
```

Generate a secure 64-character random key for session encryption:
```bash
openssl rand -hex 32
```

Edit `.env` using nano or vim:
```bash
nano .env
```

Verify and customize the following settings:
- `CADDY_HOST=outreach.weblinxsolution.com`
- `BASE_URL=https://outreach.weblinxsolution.com`
- `POSTGRES_PASSWORD=<A_STRONG_PASSWORD>`
- `JWT_SECRET_KEY=<OUTPUT_FROM_OPENSSL_ABOVE>`
- `GOOGLE_CLIENT_ID` & `GOOGLE_CLIENT_SECRET` (from Google Cloud Console)
- `OFFICE365_CLIENT_ID` & `OFFICE365_CLIENT_SECRET` (from Azure Portal)

### 4.3. Run Automated Deployment
Make deployment scripts executable and run `deploy.sh`:

```bash
chmod +x scripts/*.sh
./scripts/deploy.sh
```

The script will:
1. Build the production Docker image containing React frontend and Python FastAPI backend.
2. Initialize the PostgreSQL 15 container with persistent storage volume `weblinx_outreach_pgdata`.
3. Start the Caddy reverse proxy to automatically obtain a Let's Encrypt SSL certificate for `outreach.weblinxsolution.com`.
4. Run all database migrations idempotently.

---

## 5. Google Workspace & Microsoft 365 OAuth Setup

To enable sending through Google Workspace / Gmail and Microsoft 365 / Outlook:

### Google Cloud Console:
1. Visit [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select your project.
3. Enable **Gmail API**.
4. In **OAuth consent screen**, set user type (External or Internal).
5. In **Credentials** -> **OAuth Client ID** (Web application):
   - **Authorized JavaScript origins:** `https://outreach.weblinxsolution.com`
   - **Authorized redirect URIs:** `https://outreach.weblinxsolution.com/api/auth/google/callback`
6. Copy Client ID and Client Secret into your `.env`.

### Microsoft Azure Portal:
1. Visit [Azure Portal](https://portal.azure.com/) -> **Microsoft Entra ID** -> **App registrations**.
2. Click **New registration** (Accounts in any organizational directory and personal Microsoft accounts).
3. Under **Redirect URI**, select **Web** and enter:
   `https://outreach.weblinxsolution.com/api/auth/office365/callback`
4. Under **Certificates & secrets**, create a new Client Secret.
5. Under **API permissions**, add:
   - `Mail.ReadWrite`
   - `Mail.Send`
   - `offline_access`
   - `User.Read`
6. Copy Application (client) ID and Client Secret into your `.env`.

After updating `.env`, apply changes with:
```bash
docker compose restart app
```

---

## 6. Automated Daily Backups

Set up an automated daily backup cron job:

```bash
crontab -e
```

Add this line to back up the database every night at 2:00 AM:
```cron
0 2 * * * /opt/weblinx-outreach/scripts/backup.sh >> /var/log/weblinx_backup.log 2>&1
```

To restore from a backup:
```bash
./scripts/restore.sh backups/weblinx_outreach_backup_YYYYMMDD_HHMMSS.sql.gz
```

---

## 7. Ongoing Git-Based Updates

To deploy new updates from your git repository safely:

```bash
cd /opt/weblinx-outreach
git pull origin weblinx-main
./scripts/deploy.sh
```

Your database and settings will remain completely intact in the persistent Docker volume.
