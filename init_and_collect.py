#!/usr/bin/env python3
"""Initialize database and collect initial data."""

import os
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.storage.db import init_db, get_db
from app.collectors.mempool import MempoolCollector
from app.collectors.bitnodes import BitnodesCollector
from app.collectors.blockchain_charts import BlockchainChartsCollector
from app.collectors.bitcoin_core import BitcoinCoreCollector
from app.collectors.binance import BinanceCollector
from app.collectors.lnd import LNDCollector
from app.compute.scores import ScoreCalculator
from app.compute.formulas import MetricCalculator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Main initialization and collection function."""
    
    # Ensure data directory exists
    os.makedirs('data', exist_ok=True)
    
    # Initialize database
    logger.info("Initializing database...")
    init_db()
    
    # Verify database was created
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        logger.info(f"Created {len(tables)} tables")
        for table in tables:
            logger.info(f"  - {table['name']}")
    
    # Collect initial data
    logger.info("\nCollecting initial data from APIs...")
    
    # Initialize collectors
    mempool_collector = MempoolCollector()
    bitnodes_collector = BitnodesCollector()
    blockchain_collector = BlockchainChartsCollector()
    bitcoin_core_collector = BitcoinCoreCollector()
    binance_collector = BinanceCollector()
    lnd_collector = LNDCollector()
    
    try:
        logger.info("1. Collecting mempool data...")
        mempool_collector.collect()
        logger.info("   ✓ Mempool data collected")
    except Exception as e:
        logger.error(f"   ✗ Failed to collect mempool data: {e}")
    
    try:
        logger.info("2. Collecting Bitnodes snapshot...")
        bitnodes_collector.collect()
        logger.info("   ✓ Bitnodes snapshot collected")
    except Exception as e:
        logger.error(f"   ✗ Failed to collect Bitnodes snapshot: {e}")
    
    try:
        logger.info("3. Collecting blockchain charts data...")
        blockchain_collector.collect()
        logger.info("   ✓ Blockchain charts data collected")
    except Exception as e:
        logger.error(f"   ✗ Failed to collect blockchain charts data: {e}")
    
    try:
        logger.info("4. Collecting Bitcoin Core data (via Tor)...")
        bitcoin_core_collector.collect()
        logger.info("   ✓ Bitcoin Core data collected")
    except Exception as e:
        logger.error(f"   ✗ Failed to collect Bitcoin Core data: {e}")
    
    try:
        logger.info("5. Collecting Binance price data...")
        binance_collector.collect()
        logger.info("   ✓ Binance price data collected")
    except Exception as e:
        logger.error(f"   ✗ Failed to collect Binance data: {e}")
    
    try:
        logger.info("6. Collecting Lightning Network data (LND)...")
        lnd_collector.collect()
        logger.info("   ✓ Lightning Network data collected")
    except Exception as e:
        logger.error(f"   ✗ Failed to collect LND data: {e}")
    
    # Compute metrics first
    logger.info("\nComputing metrics...")
    try:
        metric_calc = MetricCalculator()
        metric_calc.calculate_all()
        logger.info("✓ Metrics computed successfully")
    except Exception as e:
        logger.error(f"✗ Failed to compute metrics: {e}")
    
    # Then compute scores
    logger.info("Computing scores...")
    try:
        calculator = ScoreCalculator()
        calculator.calculate_all()
        logger.info("✓ Scores computed successfully")
    except Exception as e:
        logger.error(f"✗ Failed to compute scores: {e}")
    
    # Check what data we have
    logger.info("\nChecking collected data...")
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Check raw data tables
        raw_tables = [
            'raw_mempool_snapshot',
            'raw_difficulty_estimate',
            'raw_bitnodes_snapshot',
            'raw_price',
            'raw_pool_shares'
        ]
        
        for table in raw_tables:
            cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
            count = cursor.fetchone()['count']
            logger.info(f"  {table}: {count} records")
        
        # Check computed data
        cursor.execute("SELECT COUNT(*) as count FROM metrics")
        metrics_count = cursor.fetchone()['count']
        logger.info(f"  metrics: {metrics_count} records")
        
        cursor.execute("SELECT COUNT(*) as count FROM scores")
        scores_count = cursor.fetchone()['count']
        logger.info(f"  scores: {scores_count} records")
    
    logger.info("\n✓ Initialization complete!")
    logger.info("You can now test the API at http://localhost:8080")
    logger.info("And view the dashboard at http://localhost:8000")

if __name__ == "__main__":
    main()
