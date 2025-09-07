# Bitcoin Health Scorecard - Setup Guide

## Resolving Remaining Issues

### 1. Bitcoin Core Integration (Recommended if you have a node)

If you have a Bitcoin node running, you can get much better data directly from it:

#### Option A: Using Cookie Authentication (Easiest)
```bash
# Find your bitcoin cookie file (usually in ~/.bitcoin/.cookie or /var/lib/bitcoind/.cookie)
sudo find / -name ".cookie" 2>/dev/null | grep bitcoin

# Give your user read access to the cookie
sudo usermod -a -G bitcoin $USER
# Log out and back in for group changes to take effect
```

#### Option B: Configure RPC Credentials
1. Edit your bitcoin.conf:
```bash
# Add these lines to your bitcoin.conf
rpcuser=yourusername
rpcpassword=yourpassword
rpcallowip=127.0.0.1
```

2. Create .env file:
```bash
cp .env.example .env
# Edit .env and add:
BITCOIN_RPC_USER=yourusername
BITCOIN_RPC_PASS=yourpassword
```

3. Restart Bitcoin Core:
```bash
sudo systemctl restart bitcoind
```

### 2. CoinGecko API (For Price History)

The free CoinGecko API is limited but still useful:

1. Get a free API key: https://www.coingecko.com/en/api/pricing
2. Add to .env:
```bash
COINGECKO_API_KEY=your-api-key-here
```

Alternative: Use the demo key for testing:
```bash
COINGECKO_API_KEY=CG-DEMO-API-KEY
```

### 3. Fix Large Number Storage (Hashrate)

The hashrate values from some APIs are too large for SQLite INTEGER. Already fixed by:
- Using REAL type for large values
- Storing hashrate in TH/s instead of H/s

### 4. Bitnodes SSL Certificate Issue

Already fixed by disabling SSL verification for Bitnodes collector only.
The collector will now work despite the certificate mismatch.

### 5. Alternative Data Sources (No Authentication Required)

These APIs work without any setup:

- **Blockchain.com Charts**: Historical data for most metrics
- **Mempool.space**: Real-time mempool, mining pools, fees
- **Blockchair**: Network statistics
- **BlockCypher**: Network info (limited free tier)

### 6. Testing Your Setup

Test individual collectors:
```bash
# Test Bitcoin Core connection (if configured)
/home/steven/projects/btc-health/venv/bin/python3 -m app.collectors.bitcoin_core

# Test other collectors
/home/steven/projects/btc-health/venv/bin/python3 init_and_collect.py

# Check the database
sqlite3 data/btc_health.db "SELECT COUNT(*) FROM metrics;"
```

### 7. Monitor Data Collection

Check logs:
```bash
# View recent collection logs
tail -f data/collection.log

# Check cron job is running
crontab -l | grep btc-health

# Check systemd services
systemctl status btc-health-api
systemctl status btc-health-frontend
```

### 8. Verify Website Display

The website should now show:
- Overall Bitcoin health score
- Five pillar scores (Security, Decentralization, Throughput, Adoption, Lightning)
- Historical trends (after 24-48 hours of data collection)

Access at: https://bitcoin-health.steven-geller.com

### 9. Optional Enhancements

#### Add Lightning Network Data
If you run a Lightning node:
- Configure LND/CLN RPC access
- Create Lightning collector

#### Add Tor Network Metrics
- Use Tor metrics API
- Track .onion node count

#### Enhanced Price Data
- Add multiple price sources (Kraken, Binance, etc.)
- Calculate price volatility metrics

## Troubleshooting

### Issue: No scores displayed
**Solution**: Wait 24-48 hours for data accumulation, or run manual backfill

### Issue: "Database is locked"
**Solution**: Stop duplicate collectors, check file permissions

### Issue: API rate limits
**Solution**: Adjust collection frequency in cron, use local node data

### Issue: SSL/Certificate errors
**Solution**: Update CA certificates: `sudo update-ca-certificates`

## Support

For issues, check:
- Logs: `/home/steven/projects/btc-health/data/collection.log`
- Database: `sqlite3 data/btc_health.db ".tables"`
- Services: `systemctl status btc-health-*`