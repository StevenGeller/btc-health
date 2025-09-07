#!/usr/bin/env python3
"""Backfill real historical data from free APIs."""

import sys
import os
import time
import logging
import requests
from pathlib import Path
from datetime import datetime, timedelta, timezone
import json

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.storage.db import init_db, store_json_data, execute_query, execute_insert, upsert_metric
from app.compute.formulas import MetricCalculator
from app.compute.scores import ScoreCalculator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BlockchainChartsCollector:
    """Collect historical data from Blockchain.com charts API."""
    
    def __init__(self):
        self.base_url = "https://api.blockchain.info/charts"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Bitcoin-Health-Scorecard/1.0'
        })
    
    def fetch_chart(self, chart_name, timespan="30days"):
        """Fetch a specific chart from Blockchain.com."""
        try:
            url = f"{self.base_url}/{chart_name}"
            params = {
                'timespan': timespan,
                'format': 'json'
            }
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch {chart_name}: {e}")
            return None
    
    def collect_price_history(self):
        """Collect historical price data."""
        logger.info("Fetching price history from Blockchain.com...")
        data = self.fetch_chart('market-price', '30days')
        
        if data and 'values' in data:
            count = 0
            for point in data['values']:
                ts = point['x']
                price = point['y']
                
                # Store raw price data
                store_json_data('raw_price', {
                    'ts': ts,
                    'price_usd': price,
                    'volume_24h': 0,
                    'market_cap': price * 19500000  # Approximate supply
                })
                count += 1
            
            logger.info(f"  Stored {count} price data points")
            return True
        return False
    
    def collect_hashrate_history(self):
        """Collect historical hashrate data."""
        logger.info("Fetching hashrate history from Blockchain.com...")
        data = self.fetch_chart('hash-rate', '30days')
        
        if data and 'values' in data:
            count = 0
            for point in data['values']:
                ts = point['x']
                hashrate = point['y'] * 1e9  # Convert to H/s
                
                # Store as metric
                upsert_metric('security.hashrate', hashrate, ts, 'H/s')
                count += 1
            
            logger.info(f"  Stored {count} hashrate data points")
            return True
        return False
    
    def collect_difficulty_history(self):
        """Collect historical difficulty data."""
        logger.info("Fetching difficulty history from Blockchain.com...")
        data = self.fetch_chart('difficulty', '30days')
        
        if data and 'values' in data:
            count = 0
            for point in data['values']:
                ts = point['x']
                difficulty = point['y']
                
                # Store as metric
                upsert_metric('security.difficulty', difficulty, ts)
                count += 1
            
            logger.info(f"  Stored {count} difficulty data points")
            return True
        return False
    
    def collect_mempool_size_history(self):
        """Collect historical mempool size."""
        logger.info("Fetching mempool size history from Blockchain.com...")
        data = self.fetch_chart('mempool-size', '30days')
        
        if data and 'values' in data:
            count = 0
            for point in data['values']:
                ts = point['x']
                size_bytes = point['y']
                
                # Store as metric
                upsert_metric('throughput.mempool_bytes', size_bytes, ts, 'bytes')
                count += 1
            
            logger.info(f"  Stored {count} mempool size data points")
            return True
        return False
    
    def collect_transaction_history(self):
        """Collect historical transaction counts."""
        logger.info("Fetching transaction count history from Blockchain.com...")
        data = self.fetch_chart('n-transactions', '30days')
        
        if data and 'values' in data:
            count = 0
            for point in data['values']:
                ts = point['x']
                tx_count = point['y']
                
                # Calculate transactions per block (144 blocks per day average)
                tx_per_block = tx_count / 144
                upsert_metric('throughput.tx_per_block', tx_per_block, ts)
                count += 1
            
            logger.info(f"  Stored {count} transaction count data points")
            return True
        return False
    
    def collect_utxo_history(self):
        """Collect historical UTXO count."""
        logger.info("Fetching UTXO count history from Blockchain.com...")
        data = self.fetch_chart('utxo-count', '30days')
        
        if data and 'values' in data:
            count = 0
            for i, point in enumerate(data['values']):
                ts = point['x']
                utxo_count = point['y']
                
                # Store as metric
                upsert_metric('adoption.utxo_count', utxo_count, ts)
                
                # Calculate daily change if we have previous data
                if i > 0:
                    prev_count = data['values'][i-1]['y']
                    change_pct = ((utxo_count - prev_count) / prev_count) * 100
                    upsert_metric('adoption.utxo_growth', change_pct, ts, '%')
                
                count += 1
            
            logger.info(f"  Stored {count} UTXO count data points")
            return True
        return False
    
    def collect_all(self):
        """Collect all available historical data."""
        self.collect_price_history()
        time.sleep(1)  # Rate limiting
        
        self.collect_hashrate_history()
        time.sleep(1)
        
        self.collect_difficulty_history()
        time.sleep(1)
        
        self.collect_mempool_size_history()
        time.sleep(1)
        
        self.collect_transaction_history()
        time.sleep(1)
        
        self.collect_utxo_history()


class ExtendedMempoolCollector:
    """Extended collector for Mempool.space historical data."""
    
    def __init__(self):
        self.base_url = "https://mempool.space/api"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Bitcoin-Health-Scorecard/1.0'
        })
    
    def collect_mining_pools_history(self):
        """Collect historical mining pool distribution."""
        intervals = ['1w', '1m', '3m']
        
        for interval in intervals:
            logger.info(f"Fetching mining pool data for {interval} from Mempool.space...")
            
            try:
                response = self.session.get(f"{self.base_url}/v1/mining/pools/{interval}")
                response.raise_for_status()
                data = response.json()
                
                if 'pools' in data:
                    # Use current timestamp minus appropriate offset
                    now = int(datetime.now(timezone.utc).timestamp())
                    if interval == '1w':
                        ts = now - (7 * 86400)
                    elif interval == '1m':
                        ts = now - (30 * 86400)
                    else:  # 3m
                        ts = now - (90 * 86400)
                    
                    # Store pool distribution
                    for pool in data['pools']:
                        store_json_data('raw_pool_shares', {
                            'ts': ts,
                            'pool': pool.get('name', 'Unknown'),
                            'share': pool.get('share', 0),
                            'blocks': pool.get('blockCount', 0)
                        })
                    
                    # Calculate HHI for this snapshot
                    shares = [p.get('share', 0) for p in data['pools']]
                    total = sum(shares)
                    if total > 0:
                        normalized = [s/total for s in shares]
                        hhi = sum(s**2 for s in normalized)
                        upsert_metric('decent.pool_hhi', hhi, ts)
                    
                    logger.info(f"  Stored pool distribution for {interval}")
                
                time.sleep(1)  # Rate limiting
                
            except Exception as e:
                logger.error(f"Failed to fetch pool data for {interval}: {e}")
    
    def collect_hashrate_history(self):
        """Collect historical hashrate data."""
        intervals = ['1m', '3m']
        
        for interval in intervals:
            logger.info(f"Fetching hashrate history for {interval} from Mempool.space...")
            
            try:
                response = self.session.get(f"{self.base_url}/v1/mining/hashrate/{interval}")
                response.raise_for_status()
                data = response.json()
                
                if 'hashrates' in data:
                    count = 0
                    for point in data['hashrates']:
                        ts = point['timestamp']
                        hashrate = point['avgHashrate']
                        
                        upsert_metric('security.hashrate', hashrate, ts, 'H/s')
                        count += 1
                    
                    logger.info(f"  Stored {count} hashrate points for {interval}")
                
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Failed to fetch hashrate for {interval}: {e}")
    
    def collect_recent_blocks(self):
        """Collect recent block data for fee analysis."""
        logger.info("Fetching recent blocks from Mempool.space...")
        
        try:
            # Get last 15 blocks
            response = self.session.get(f"{self.base_url}/v1/blocks/0")
            response.raise_for_status()
            blocks = response.json()
            
            total_fees = []
            block_sizes = []
            tx_counts = []
            
            for block in blocks:
                if 'extras' in block and 'totalFees' in block['extras']:
                    fees_btc = block['extras']['totalFees'] / 1e8
                    total_fees.append(fees_btc)
                    
                if 'size' in block:
                    block_sizes.append(block['size'] / 1e6)  # MB
                    
                if 'tx_count' in block:
                    tx_counts.append(block['tx_count'])
                    
                ts = block.get('timestamp', int(time.time()))
                
                # Store metrics
                if 'tx_count' in block:
                    upsert_metric('throughput.tx_per_block', block['tx_count'], ts)
                    
                if 'size' in block:
                    upsert_metric('chain.avg_block_size', block['size'] / 1e6, ts, 'MB')
            
            # Calculate and store averages
            if total_fees:
                avg_fees = sum(total_fees) / len(total_fees)
                current_ts = int(time.time())
                upsert_metric('fees.avg_block_reward', avg_fees, current_ts, 'BTC')
                
                # Calculate fee share (fees vs subsidy)
                subsidy = 3.125  # Current subsidy
                fee_share = (avg_fees / (avg_fees + subsidy)) * 100
                upsert_metric('security.fee_share', fee_share, current_ts, '%')
            
            logger.info(f"  Processed {len(blocks)} recent blocks")
            
        except Exception as e:
            logger.error(f"Failed to fetch recent blocks: {e}")
    
    def collect_all(self):
        """Collect all extended Mempool.space data."""
        self.collect_mining_pools_history()
        self.collect_hashrate_history()
        self.collect_recent_blocks()


class BlockchairCollector:
    """Collect data from Blockchair API."""
    
    def __init__(self):
        self.base_url = "https://api.blockchair.com/bitcoin"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Bitcoin-Health-Scorecard/1.0'
        })
    
    def collect_stats(self):
        """Collect current Bitcoin network statistics."""
        logger.info("Fetching Bitcoin stats from Blockchair...")
        
        try:
            response = self.session.get(f"{self.base_url}/stats")
            response.raise_for_status()
            data = response.json()
            
            if 'data' in data:
                stats = data['data']
                ts = int(time.time())
                
                # Store various metrics
                if 'hashrate_24h' in stats:
                    upsert_metric('security.hashrate_24h', stats['hashrate_24h'], ts, 'H/s')
                
                if 'mempool_transactions' in stats:
                    upsert_metric('throughput.mempool_count', stats['mempool_transactions'], ts)
                
                if 'mempool_size' in stats:
                    upsert_metric('throughput.mempool_bytes', stats['mempool_size'], ts, 'bytes')
                
                if 'suggested_transaction_fee_per_byte_sat' in stats:
                    upsert_metric('fees.suggested', stats['suggested_transaction_fee_per_byte_sat'], ts, 'sat/B')
                
                if 'average_transaction_fee_24h' in stats:
                    upsert_metric('fees.avg_24h', stats['average_transaction_fee_24h'], ts, 'sat')
                
                logger.info("  Stored Blockchair stats")
                return True
                
        except Exception as e:
            logger.error(f"Failed to fetch Blockchair stats: {e}")
            return False
    
    def collect_all(self):
        """Collect all Blockchair data."""
        self.collect_stats()


def calculate_percentiles():
    """Calculate percentiles for all metrics with sufficient data."""
    logger.info("Calculating percentiles for metrics...")
    
    # Get all unique metric IDs
    metric_ids = execute_query("""
        SELECT DISTINCT metric_id FROM metrics
    """)
    
    for row in metric_ids:
        metric_id = row['metric_id']
        
        # Get all values for this metric
        values = execute_query("""
            SELECT value FROM metrics 
            WHERE metric_id = ? 
            ORDER BY value
        """, (metric_id,))
        
        if len(values) >= 10:  # Need at least 10 data points
            value_list = [v['value'] for v in values]
            
            # Calculate percentiles
            import numpy as np
            p10 = np.percentile(value_list, 10)
            p25 = np.percentile(value_list, 25)
            p50 = np.percentile(value_list, 50)
            p75 = np.percentile(value_list, 75)
            p90 = np.percentile(value_list, 90)
            
            # Store percentiles
            execute_insert("""
                INSERT OR REPLACE INTO percentiles 
                (metric_id, p10, p25, p50, p75, p90, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (metric_id, p10, p25, p50, p75, p90, int(time.time())))
            
            logger.debug(f"  Calculated percentiles for {metric_id}")
    
    logger.info("  Percentile calculation complete")


def main():
    """Run the backfill process."""
    logger.info("Starting real data backfill...")
    logger.info("=" * 60)
    
    # Collect from Blockchain.com charts
    logger.info("\n1. Collecting from Blockchain.com Charts API...")
    blockchain_collector = BlockchainChartsCollector()
    blockchain_collector.collect_all()
    
    # Collect from extended Mempool.space
    logger.info("\n2. Collecting from Mempool.space API...")
    mempool_collector = ExtendedMempoolCollector()
    mempool_collector.collect_all()
    
    # Collect from Blockchair
    logger.info("\n3. Collecting from Blockchair API...")
    blockchair_collector = BlockchairCollector()
    blockchair_collector.collect_all()
    
    # Calculate metrics from collected data
    logger.info("\n4. Computing derived metrics...")
    calculator = MetricCalculator()
    
    # Get all unique timestamps
    timestamps = execute_query("""
        SELECT DISTINCT ts FROM (
            SELECT ts FROM metrics
            UNION SELECT ts FROM raw_price
        ) ORDER BY ts
        LIMIT 100
    """)
    
    for row in timestamps[:50]:  # Process first 50 timestamps
        try:
            calculator.calculate_all()
        except Exception as e:
            logger.debug(f"Metric calculation error (expected for partial data): {e}")
    
    # Calculate percentiles
    logger.info("\n5. Calculating percentiles...")
    calculate_percentiles()
    
    # Calculate scores
    logger.info("\n6. Calculating scores...")
    scorer = ScoreCalculator()
    scorer.calculate_all()
    
    # Report results
    logger.info("\n" + "=" * 60)
    logger.info("BACKFILL COMPLETE!")
    logger.info("=" * 60)
    
    # Check what we have
    metrics_count = execute_query("SELECT COUNT(*) as count FROM metrics")[0]['count']
    prices_count = execute_query("SELECT COUNT(*) as count FROM raw_price")[0]['count']
    percentiles_count = execute_query("SELECT COUNT(*) as count FROM percentiles")[0]['count']
    scores_count = execute_query("SELECT COUNT(*) as count FROM scores")[0]['count']
    
    logger.info(f"Database now contains:")
    logger.info(f"  - {metrics_count} metric data points")
    logger.info(f"  - {prices_count} price data points")
    logger.info(f"  - {percentiles_count} percentile records")
    logger.info(f"  - {scores_count} score records")
    
    if scores_count > 0:
        logger.info("\n✓ The dashboard should now display scores!")
    else:
        logger.info("\n⚠ Still building historical data. Scores will appear soon.")


if __name__ == '__main__':
    main()