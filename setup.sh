#!/bin/bash
# Quick setup script for Bitcoin Health Scorecard

echo "Bitcoin Health Scorecard - Setup Script"
echo "======================================="

# Check Python version
python_version=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
required_version="3.8"

if [ "$(printf '%s\n' "$required_version" "$python_version" | sort -V | head -n1)" != "$required_version" ]; then
    echo "Error: Python 3.8 or higher is required (found $python_version)"
    exit 1
fi

echo "✓ Python version: $python_version"

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cat > .env << EOF
# API Base URLs (optional - defaults are set in code)
MEMPOOL_API_BASE=https://mempool.space/api
BITNODES_API_BASE=https://bitnodes.io/api/v1
BLOCKCHAIN_API_BASE=https://api.blockchain.info
COINGECKO_API_BASE=https://api.coingecko.com/api/v3
FORKMONITOR_BASE=https://forkmonitor.info

# Database
DB_PATH=btc_health.db

# API Server
API_HOST=0.0.0.0
API_PORT=8080
EOF
    echo "✓ Created .env file"
else
    echo "✓ .env file already exists"
fi

# Initialize database
echo "Initializing database..."
sqlite3 btc_health.db < app/storage/schema.sql
echo "✓ Database initialized"

# Run initial data collection
echo ""
echo "Would you like to run initial data collection? (y/n)"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
    echo "Running initial collectors..."
    python scripts/backfill.py --days 1
fi

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Activate virtual environment: source venv/bin/activate"
echo "2. Run API server: uvicorn app.api.server:app --reload"
echo "3. Access API at: http://localhost:8080"
echo "4. Set up cron jobs for automated collection (see README.md)"
echo ""
echo "For full historical backfill (may take time):"
echo "  python scripts/backfill.py --days 30"
