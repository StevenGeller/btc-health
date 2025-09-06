#!/bin/bash
# Production deployment script for Bitcoin Health Scorecard

set -e

# Configuration
INSTALL_DIR="/opt/btc-health"
SERVICE_USER="bitcoin"
SERVICE_GROUP="bitcoin"
REPO_URL="https://github.com/yourusername/btc-health.git"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Bitcoin Health Scorecard - Production Deployment${NC}"
echo "================================================"

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root (use sudo)${NC}"
    exit 1
fi

# 1. System dependencies
echo -e "${YELLOW}Installing system dependencies...${NC}"
apt-get update
apt-get install -y \
    python3.9 \
    python3.9-venv \
    python3-pip \
    sqlite3 \
    nginx \
    certbot \
    python3-certbot-nginx \
    git \
    supervisor

# 2. Create service user
echo -e "${YELLOW}Creating service user...${NC}"
if ! id "$SERVICE_USER" &>/dev/null; then
    useradd -r -s /bin/false -d /nonexistent "$SERVICE_USER"
    echo -e "${GREEN}Created user: $SERVICE_USER${NC}"
else
    echo "User $SERVICE_USER already exists"
fi

# 3. Create installation directory
echo -e "${YELLOW}Setting up installation directory...${NC}"
mkdir -p "$INSTALL_DIR"
chown "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"

# 4. Clone or update repository
echo -e "${YELLOW}Getting application code...${NC}"
if [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR"
    sudo -u "$SERVICE_USER" git pull
else
    cd "$(dirname "$INSTALL_DIR")"
    sudo -u "$SERVICE_USER" git clone "$REPO_URL" "$(basename "$INSTALL_DIR")"
fi

cd "$INSTALL_DIR"

# 5. Set up Python virtual environment
echo -e "${YELLOW}Setting up Python environment...${NC}"
sudo -u "$SERVICE_USER" python3.9 -m venv venv
sudo -u "$SERVICE_USER" ./venv/bin/pip install --upgrade pip
sudo -u "$SERVICE_USER" ./venv/bin/pip install -r requirements.txt

# 6. Initialize database
echo -e "${YELLOW}Initializing database...${NC}"
if [ ! -f "$INSTALL_DIR/btc_health.db" ]; then
    sudo -u "$SERVICE_USER" sqlite3 btc_health.db < app/storage/schema.sql
    echo -e "${GREEN}Database initialized${NC}"
else
    echo "Database already exists"
fi

# 7. Set up environment file
echo -e "${YELLOW}Configuring environment...${NC}"
if [ ! -f "$INSTALL_DIR/.env" ]; then
    cat > "$INSTALL_DIR/.env" << EOF
# Production Configuration
MEMPOOL_API_BASE=https://mempool.space/api
BITNODES_API_BASE=https://bitnodes.io/api/v1
BLOCKCHAIN_API_BASE=https://api.blockchain.info
COINGECKO_API_BASE=https://api.coingecko.com/api/v3
FORKMONITOR_BASE=https://forkmonitor.info

DB_PATH=$INSTALL_DIR/btc_health.db

API_HOST=127.0.0.1
API_PORT=8080
EOF
    chown "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR/.env"
    chmod 600 "$INSTALL_DIR/.env"
    echo -e "${GREEN}Environment configured${NC}"
else
    echo "Environment file already exists"
fi

# 8. Install systemd services
echo -e "${YELLOW}Installing systemd services...${NC}"
cp deploy/systemd/*.service /etc/systemd/system/
cp deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload

# 9. Enable and start services
echo -e "${YELLOW}Starting services...${NC}"
systemctl enable btc-health-api.service
systemctl enable btc-health-collector.timer
systemctl enable btc-health-compute.timer

systemctl start btc-health-api.service
systemctl start btc-health-collector.timer
systemctl start btc-health-compute.timer

# 10. Configure Nginx
echo -e "${YELLOW}Configuring Nginx...${NC}"
cp deploy/nginx.conf /etc/nginx/sites-available/btc-health

# Update server_name in nginx config
read -p "Enter your domain name (e.g., btc-health.example.com): " DOMAIN
sed -i "s/btc-health.example.com/$DOMAIN/g" /etc/nginx/sites-available/btc-health

ln -sf /etc/nginx/sites-available/btc-health /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# 11. Set up SSL with Let's Encrypt
echo -e "${YELLOW}Setting up SSL certificate...${NC}"
read -p "Set up SSL certificate with Let's Encrypt? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    certbot --nginx -d "$DOMAIN"
fi

# 12. Set up log rotation
echo -e "${YELLOW}Configuring log rotation...${NC}"
cat > /etc/logrotate.d/btc-health << EOF
$INSTALL_DIR/logs/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 640 $SERVICE_USER $SERVICE_GROUP
    sharedscripts
    postrotate
        systemctl reload btc-health-api.service > /dev/null 2>&1 || true
    endscript
}
EOF

# 13. Run initial data collection
echo -e "${YELLOW}Running initial data collection...${NC}"
sudo -u "$SERVICE_USER" ./venv/bin/python scripts/backfill.py --days 1

# 14. Set up monitoring (optional)
echo -e "${YELLOW}Setting up monitoring...${NC}"
cat > /usr/local/bin/btc-health-monitor.sh << 'EOF'
#!/bin/bash
# Simple monitoring script

API_URL="http://localhost:8080/health"
ALERT_EMAIL="admin@example.com"

# Check API health
if ! curl -f -s "$API_URL" > /dev/null; then
    echo "Bitcoin Health Scorecard API is down!" | mail -s "BTC Health Alert" "$ALERT_EMAIL"
    systemctl restart btc-health-api.service
fi

# Check database size
DB_SIZE=$(du -h /opt/btc-health/btc_health.db | cut -f1)
echo "Database size: $DB_SIZE"

# Check last collection time
LAST_COLLECTION=$(sqlite3 /opt/btc-health/btc_health.db "SELECT value FROM meta_config WHERE key='last_collection'")
echo "Last collection: $LAST_COLLECTION"
EOF

chmod +x /usr/local/bin/btc-health-monitor.sh

# Add to crontab
(crontab -l 2>/dev/null; echo "*/5 * * * * /usr/local/bin/btc-health-monitor.sh") | crontab -

# 15. Display status
echo
echo -e "${GREEN}Deployment Complete!${NC}"
echo "==================="
echo
echo "Service Status:"
systemctl status btc-health-api.service --no-pager | head -n 3
echo
echo "API Endpoint: https://$DOMAIN/api/"
echo "Frontend: https://$DOMAIN/"
echo
echo "Commands:"
echo "  View API logs: journalctl -u btc-health-api -f"
echo "  View collector logs: journalctl -u btc-health-collector -f"
echo "  Restart API: systemctl restart btc-health-api"
echo "  Check status: systemctl status btc-health-api"
echo
echo "Database location: $INSTALL_DIR/btc_health.db"
echo
echo -e "${YELLOW}Remember to:${NC}"
echo "1. Update the ALERT_EMAIL in /usr/local/bin/btc-health-monitor.sh"
echo "2. Configure firewall rules if needed"
echo "3. Set up backups for the database"
echo "4. Monitor disk space and logs"
