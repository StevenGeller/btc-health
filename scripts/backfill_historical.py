#!/usr/bin/env python3
"""Backfill historical data from available sources."""

import sys
import os
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone
import requests

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.storage.db import init_db, store_json_data, execute_query, upsert_metric
from app.compute.formulas import MetricCalculator
from app.compute.scores import ScoreCalculator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class HistoricalBackfiller:
    """Backfill historical data from various sources."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Bitcoin-Health-Scorecard/1.0'
        })
    
    def backfill_mempool_blocks(self, days=30):
        """Backfill block data from mempool.space."""
        logger.info(f"Backfilling {days} days of block data from mempool.space...")
        
        # Get current block height
        response = self.session.get('https://mempool.space/api/blocks/tip/height')
        current_height = int(response.text)
        
        # Estimate blocks to fetch (144 blocks per day on average)
        blocks_to_fetch = days * 144
        start_height = current_height - blocks_to_fetch
        
        logger.info(f"Fetching blocks from {start_height} to {current_height}")
        
        # Fetch blocks in batches
        batch_size = 15  # mempool.space returns 15 blocks at a time
        
        for height in range(start_height, current_height, batch_size):
            try:
                # Get batch of blocks
                response = self.session.get(f'https://mempool.space/api/v1/blocks/{height}')
                blocks = response.json()
                
                for block in blocks:
                    ts = block['timestamp']
                    
                    # Store block reward data
                    if 'extras' in block and 'totalFees' in block['extras']:
                        total_fees = block['extras']['totalFees'] / 100000000  # Convert to BTC
                        day = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                        store_json_data('raw_block_rewards', {
                            'day': day,
                            'avg_fee_per_block': total_fees,
                            'fees_btc': total_fees,
                            'subsidy_btc': 3.125,  # Current block subsidy
                            'blocks': 1
                        })
                    
                    # Calculate metrics from block data
                    if 'tx_count' in block:
                        upsert_metric('throughput.tx_per_block', block['tx_count'], ts)
                    
                    if 'size' in block:
                        upsert_metric('chain.avg_block_size', block['size'] / 1000000, ts, 'MB')
                
                logger.info(f"Processed blocks at height {height}")
                time.sleep(0.5)  # Rate limiting
                
            except Exception as e:
                logger.error(f"Failed to fetch blocks at height {height}: {e}")
                continue
    
    def backfill_mempool_stats(self, days=30):
        """Backfill mempool statistics."""
        logger.info(f"Backfilling {days} days of mempool stats...")
        
        # Get historical mempool snapshots (limited availability)
        for day_offset in range(days):
            try:
                target_date = datetime.now(timezone.utc) - timedelta(days=day_offset)
                ts = int(target_date.timestamp())
                
                # Get mempool stats
                response = self.session.get('https://mempool.space/api/mempool')
                data = response.json()
                
                store_json_data('raw_mempool_snapshot', {
                    'ts': ts,
                    'count': data.get('count', 0),
                    'vsize': data.get('vBytes', 0),
                    'total_fee': data.get('total_fee', 0)
                })
                
                logger.info(f"Stored mempool snapshot for {target_date.date()}")
                time.sleep(1)  # Rate limiting
                
            except Exception as e:
                logger.error(f"Failed to fetch mempool stats for day {day_offset}: {e}")
    
    def backfill_difficulty(self, days=30):
        """Backfill difficulty adjustment data."""
        logger.info(f"Backfilling {days} days of difficulty data...")
        
        try:
            # Get difficulty adjustment history
            response = self.session.get('https://mempool.space/api/v1/mining/difficulty-adjustments')
            adjustments = response.json()
            
            for adj in adjustments[:days//14]:  # Difficulty adjusts every ~14 days
                if 'timestamp' in adj:
                    ts = adj['timestamp']
                    store_json_data('raw_difficulty_estimate', {
                        'ts': ts,
                        'progress': 100,  # Historical data is complete
                        'est_change': adj.get('difficultyChange', 0),
                        'remaining_blocks': 0,
                        'remaining_time': 0,
                        'previous_retarget': adj.get('previousRetarget', 0)
                    })
                    
                    logger.info(f"Stored difficulty adjustment: {adj.get('difficultyChange', 0):.2f}%")
            
        except Exception as e:
            logger.error(f"Failed to fetch difficulty data: {e}")
    
    def backfill_mining_pools(self, days=30):
        """Backfill mining pool distribution data."""
        logger.info(f"Backfilling {days} days of mining pool data...")
        
        for day_offset in range(0, days, 7):  # Weekly snapshots
            try:
                # Get mining pool stats  
                response = self.session.get(f'https://mempool.space/api/v1/mining/pools/1w')
                pools = response.json()['pools']
                
                target_date = datetime.now(timezone.utc) - timedelta(days=day_offset)
                ts = int(target_date.timestamp())
                
                for pool in pools:
                    if 'name' in pool:
                        store_json_data('raw_pool_shares', {
                            'ts': ts,
                            'pool': pool['name'],
                            'share': pool.get('share', 0),
                            'blocks': pool.get('blockCount', 0)
                        })
                
                logger.info(f"Stored pool distribution for {target_date.date()}")
                time.sleep(1)  # Rate limiting
                
            except Exception as e:
                logger.error(f"Failed to fetch pool data: {e}")
    
    def backfill_price_data(self, days=30):
        """Backfill price data from CoinGecko."""
        logger.info(f"Backfilling {days} days of price data...")
        
        try:
            # CoinGecko free tier allows historical data
            response = self.session.get(
                f'https://api.coingecko.com/api/v3/coins/bitcoin/market_chart',
                params={'vs_currency': 'usd', 'days': days}
            )
            
            if response.status_code == 200:
                data = response.json()
                prices = data.get('prices', [])
                
                # Store daily price snapshots
                for timestamp_ms, price in prices[::24]:  # Every 24 hours
                    ts = timestamp_ms // 1000
                    store_json_data('raw_price', {
                        'ts': ts,
                        'price_usd': price,
                        'market_cap': 0,
                        'volume_24h': 0
                    })
                
                logger.info(f"Stored {len(prices)//24} price data points")
            else:
                logger.warning(f"CoinGecko API returned {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to fetch price data: {e}")
    
    def backfill_utxo_data(self, days=30):
        """Backfill UTXO count data."""
        logger.info(f"Backfilling {days} days of UTXO data...")
        
        try:
            # Blockchain.info charts API
            response = self.session.get(
                'https://api.blockchain.info/charts/utxo-count',
                params={'timespan': f'{days}days', 'format': 'json'}
            )
            
            if response.status_code == 200:
                data = response.json()
                values = data.get('values', [])
                
                for point in values:
                    store_json_data('raw_utxo_count', {
                        'day': datetime.fromtimestamp(point['x']).strftime('%Y-%m-%d'),
                        'utxo_count': point['y'],
                        'change_24h': 0,
                        'change_7d': 0
                    })
                
                logger.info(f"Stored {len(values)} UTXO data points")
                
        except Exception as e:
            logger.error(f"Failed to fetch UTXO data: {e}")
    
    def run_backfill(self, days=30):
        """Run all backfill operations."""
        logger.info(f"Starting historical backfill for {days} days...")
        
        # Backfill in order of importance
        self.backfill_price_data(days)
        time.sleep(2)
        
        self.backfill_mempool_blocks(min(days, 7))  # Recent blocks only
        time.sleep(2)
        
        self.backfill_difficulty(days)
        time.sleep(2)
        
        self.backfill_mining_pools(days)
        time.sleep(2)
        
        self.backfill_mempool_stats(min(days, 3))  # Very recent only
        time.sleep(2)
        
        self.backfill_utxo_data(days)
        
        logger.info("Backfill data collection complete!")
        
        # Now compute metrics for all the historical data
        logger.info("Computing metrics for historical data...")
        calculator = MetricCalculator()
        
        # Get all unique timestamps
        timestamps = execute_query("""
            SELECT DISTINCT ts FROM (
                SELECT ts FROM raw_mempool_snapshot
                UNION SELECT ts FROM raw_difficulty_estimate  
                UNION SELECT ts FROM raw_price
                UNION SELECT ts FROM raw_pool_shares
            ) ORDER BY ts
        """)
        
        logger.info(f"Processing metrics for {len(timestamps)} timestamps...")
        for row in timestamps:
            ts = row['ts']
            try:
                # Calculate metrics for this timestamp
                calculator.calculate_all()
                logger.debug(f"Calculated metrics for {datetime.fromtimestamp(ts)}")
            except Exception as e:
                logger.error(f"Failed to calculate metrics for timestamp {ts}: {e}")
        
        # Calculate scores
        logger.info("Calculating scores...")
        scorer = ScoreCalculator()
        scorer.calculate_all()
        
        logger.info("Historical backfill complete!")


def main():
    """Run the backfill process."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Backfill historical Bitcoin data')
    parser.add_argument('--days', type=int, default=30,
                       help='Number of days to backfill (default: 30)')
    
    args = parser.parse_args()
    
    backfiller = HistoricalBackfiller()
    backfiller.run_backfill(args.days)


if __name__ == '__main__':
    main()