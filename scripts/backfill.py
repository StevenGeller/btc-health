#!/usr/bin/env python3
"""Backfill historical data for Bitcoin Health Scorecard."""

import sys
import os
import argparse
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.storage.db import init_db
from app.collectors.mempool import MempoolCollector
from app.collectors.bitnodes import BitnodesCollector
from app.collectors.coingecko import CoinGeckoCollector
from app.collectors.blockchain_charts import BlockchainChartsCollector
from app.collectors.forkmonitor import ForkMonitorCollector
from app.compute.formulas import MetricCalculator
from app.compute.normalize import MetricNormalizer
from app.compute.scores import ScoreCalculator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Run backfill process."""
    parser = argparse.ArgumentParser(description='Backfill historical Bitcoin data')
    parser.add_argument('--days', type=int, default=30,
                       help='Number of days to backfill (default: 30)')
    parser.add_argument('--init-db', action='store_true',
                       help='Initialize database before backfilling')
    parser.add_argument('--skip-collectors', action='store_true',
                       help='Skip data collection (compute only)')
    parser.add_argument('--skip-compute', action='store_true',
                       help='Skip computation (collect only)')
    
    args = parser.parse_args()
    
    try:
        # Initialize database if requested
        if args.init_db:
            logger.info("Initializing database...")
            init_db()
        
        # Run collectors
        if not args.skip_collectors:
            logger.info(f"Starting backfill for {args.days} days...")
            
            collectors = [
                MempoolCollector(),
                CoinGeckoCollector(),
                BlockchainChartsCollector(),
                ForkMonitorCollector(),
                # BitnodesCollector() - Run sparingly due to rate limits
            ]
            
            # Note: For true historical backfill, you'd need to modify collectors
            # to accept date ranges and fetch historical data where available.
            # Most APIs have limited historical data access.
            
            for collector in collectors:
                logger.info(f"Running {collector.name} collector...")
                success = collector.run()
                if not success:
                    logger.warning(f"{collector.name} collector failed")
            
            # Run Bitnodes separately with caution
            if args.days <= 7:  # Only for short backfills
                logger.info("Running Bitnodes collector (rate-limited)...")
                bitnodes = BitnodesCollector()
                bitnodes.run()
        
        # Run computations
        if not args.skip_compute:
            logger.info("Running metric calculations...")
            calculator = MetricCalculator()
            calculator.calculate_all()
            
            logger.info("Running normalization...")
            normalizer = MetricNormalizer()
            normalizer.normalize_all()
            
            logger.info("Calculating scores...")
            scorer = ScoreCalculator()
            scorer.calculate_all()
        
        logger.info("Backfill completed successfully!")
        return 0
        
    except Exception as e:
        logger.error(f"Backfill failed: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
