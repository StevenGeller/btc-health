# Bitcoin Network & Mining Health Scorecard

A comprehensive Bitcoin network health monitoring system that tracks security, decentralization, throughput, adoption, and Lightning Network metrics using only public APIs.

## Overview

This system provides a 0-100 overall health score composed of five pillar scores:
- **Security & Mining Economics (30%)**: Difficulty momentum, fee share, hashprice, stale blocks
- **Decentralization & Resilience (25%)**: Mining pool concentration, node diversity, client diversity  
- **Throughput & Mempool Dynamics (15%)**: Mempool backlog, fee market elasticity, confirmation times
- **Adoption & Protocol Efficiency (15%)**: UTXO growth, SegWit/Taproot utilization, RBF activity
- **Lightning Network Vitality (15%)**: Capacity growth, channel distribution, node concentration

## Features

- **No authentication required** - Uses only public APIs
- **SQLite backend** - Simple, no Docker needed
- **Adaptive scoring** - Uses rolling percentiles to handle market regime changes
- **Minimal dependencies** - Python with standard data libraries
- **REST API** - Read-only endpoints for frontend consumption
- **Automated collection** - Cron-based data gathering

## Quick Start

### 1. Setup Environment

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp .env.example .env
```

### 2. Initialize Database

```bash
# Create database with schema
sqlite3 btc_health.db < app/storage/schema.sql

# Run initial backfill (fetches historical data)
python scripts/backfill.py --days 400
```

### 3. Start API Server

```bash
uvicorn app.api.server:app --reload --host 0.0.0.0 --port 8080
```

### 4. Setup Cron Jobs

Add to crontab for automated data collection:

```cron
# Hourly collectors
*/20 * * * * /path/to/venv/bin/python -m app.collectors.mempool
15   * * * * /path/to/venv/bin/python -m app.collectors.coingecko

# Less frequent collectors (rate-limited)
5  */6 * * * /path/to/venv/bin/python -m app.collectors.bitnodes

# Daily collectors
45  0 * * * /path/to/venv/bin/python -m app.collectors.blockchain_charts
50  0 * * * /path/to/venv/bin/python -m app.collectors.forkmonitor

# Score computation (nightly)
0   1 * * * /path/to/venv/bin/python -m app.compute.normalize && /path/to/venv/bin/python -m app.compute.scores
```

## API Endpoints

- `GET /score/latest` - Current overall and pillar scores
- `GET /score/timeseries?kind=[metric|pillar|overall]&id=...&days=...` - Historical scores
- `GET /meta` - Metric descriptions, formulas, weights, last updated

## Data Sources

All data comes from public APIs:
- **mempool.space** - Blocks, fees, mining pools, difficulty, Lightning
- **Bitnodes** - Node distribution, client versions, ASN diversity
- **Blockchain.com** - UTXO count and other chain metrics
- **CoinGecko** - BTC price data
- **ForkMonitor** - Stale blocks and reorg incidents

## Project Structure

```
btc-health/
├── app/
│   ├── collectors/      # Data collection modules
│   ├── compute/         # Score calculation logic
│   ├── storage/         # Database interface
│   └── api/            # REST API server
├── scripts/            # Utility scripts
├── requirements.txt    # Python dependencies
├── .env               # Configuration
└── btc_health.db      # SQLite database
```

## Scoring Methodology

Each metric is normalized using rolling percentiles over 365 days (90-day fallback):
- Metrics where higher is better: `score = 100 * percentile_rank(value)`
- Metrics where lower is better: `score = 100 * (1 - percentile_rank(value))`
- Target band metrics: Linear mapping with 100 at center, 0 at boundaries

Pillar scores are weighted averages of their constituent metrics.
Overall score is the weighted sum of pillar scores.

## Development

### Running Tests
```bash
pytest tests/
```

### Adding New Metrics
1. Add collector in `app/collectors/`
2. Define computation in `app/compute/formulas.py`
3. Update scoring weights in `app/compute/scores.py`
4. Add to schema if needed

## License

MIT

## Contributing

Pull requests welcome! Please ensure:
- All collectors handle rate limits gracefully
- New metrics include documentation
- Tests cover critical paths
