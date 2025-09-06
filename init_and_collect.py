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
from app.collectors.coingecko import CoinGeckoCollector
from app.collectors.blockchain_charts import BlockchainChartsCollector
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
    coingecko_collector = CoinGeckoCollector()
    blockchain_collector = BlockchainChartsCollector()
    
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
        logger.info("3. Collecting price data...")
        coingecko_collector.collect()
        logger.info("   ✓ Price data collected")
    except Exception as e:
        logger.error(f"   ✗ Failed to collect price data: {e}")
    
    try:
        logger.info("4. Collecting blockchain charts data...")
        blockchain_collector.collect()
        logger.info("   ✓ Blockchain charts data collected")
    except Exception as e:
        logger.error(f"   ✗ Failed to collect blockchain charts data: {e}")
    
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
