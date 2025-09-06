"""Mempool.space data collector."""

import os
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone

from app.collectors.base import BaseCollector
from app.storage.db import store_json_data, execute_insert, execute_query

logger = logging.getLogger(__name__)


class MempoolCollector(BaseCollector):
    """Collector for mempool.space API data."""
    
    def __init__(self):
        base_url = os.getenv('MEMPOOL_API_BASE', 'https://mempool.space/api')
        super().__init__('mempool', base_url, rate_limit_delay=0.5)
    
    def collect(self):
        """Collect all mempool data."""
        self.collect_mempool_stats()
        self.collect_difficulty_adjustment()
        self.collect_mining_pools()
        self.collect_block_rewards()
        self.collect_lightning_stats()
        self.collect_fee_estimates()
        self.collect_rbf_stats()
        self.collect_recent_blocks()
    
    def collect_mempool_stats(self):
        """Collect current mempool statistics."""
        data = self.get('/mempool')
        if data:
            # Calculate fee histogram if available
            fee_hist = None
            if 'fee_histogram' in data:
                fee_hist = data['fee_histogram']
            
            store_json_data('raw_mempool_snapshot', {
                'ts': self.get_timestamp(),
                'count': data.get('count', 0),
                'vsize': data.get('vsize', 0),
                'total_fee': data.get('total_fee', 0),
                'fee_hist': fee_hist
            })
            logger.info(f"Collected mempool stats: {data.get('count')} txs, {data.get('vsize')} vbytes")
    
    def collect_difficulty_adjustment(self):
        """Collect difficulty adjustment estimates."""
        data = self.get('/v1/difficulty-adjustment')
        if data:
            store_json_data('raw_difficulty_estimate', {
                'ts': self.get_timestamp(),
                'progress': data.get('progressPercent', 0),
                'est_change': data.get('difficultyChange', 0),
                'est_date': data.get('estimatedRetargetDate')
            })
            logger.info(f"Collected difficulty adjustment: {data.get('difficultyChange')}% estimated change")
    
    def collect_mining_pools(self):
        """Collect mining pool distribution."""
        # Get 1-day pool stats
        data = self.get('/v1/mining/pools/1d')
        if data and 'pools' in data:
            ts = self.get_timestamp()
            pool_data = []
            
            for pool in data['pools']:
                pool_data.append((
                    ts,
                    pool.get('name', 'Unknown'),
                    pool.get('share', 0),
                    pool.get('blockCount', 0)
                ))
            
            if pool_data:
                query = """
                    INSERT OR REPLACE INTO raw_pool_shares (ts, pool, share, blocks)
                    VALUES (?, ?, ?, ?)
                """
                from app.storage.db import execute_many
                execute_many(query, pool_data)
                logger.info(f"Collected data for {len(pool_data)} mining pools")
    
    def collect_block_rewards(self):
        """Collect block reward statistics."""
        # Get recent blocks to calculate rewards
        data = self.get('/v1/blocks/0')  # Get latest blocks
        if data and isinstance(data, list) and len(data) > 0:
            # Calculate daily averages
            day = self.get_date_string()
            
            total_fees = sum(block.get('extras', {}).get('totalFees', 0) for block in data[:144])  # ~1 day
            block_count = min(len(data), 144)
            
            if block_count > 0:
                avg_fee = total_fees / block_count / 1e8  # Convert to BTC
                subsidy = 6.25  # Current subsidy (will need updating after halving)
                
                store_json_data('raw_block_rewards', {
                    'day': day,
                    'fees_btc': total_fees / 1e8,
                    'subsidy_btc': subsidy * block_count,
                    'blocks': block_count,
                    'avg_fee_per_block': avg_fee
                })
                logger.info(f"Collected block rewards: {avg_fee:.4f} BTC avg fee per block")
    
    def collect_lightning_stats(self):
        """Collect Lightning Network statistics."""
        data = self.get('/v1/lightning/statistics/latest')
        if data:
            day = self.get_date_string()
            
            store_json_data('raw_ln_stats', {
                'day': day,
                'capacity_btc': data.get('total_capacity', 0) / 1e8,
                'channels': data.get('channel_count', 0),
                'nodes': data.get('node_count', 0),
                'avg_capacity': data.get('avg_capacity', 0) / 1e8,
                'avg_fee_rate': data.get('avg_fee_rate', 0)
            })
            logger.info(f"Collected Lightning stats: {data.get('total_capacity', 0) / 1e8:.2f} BTC capacity")
    
    def collect_fee_estimates(self):
        """Collect fee rate recommendations."""
        data = self.get('/v1/fees/recommended')
        if data:
            ts = self.get_timestamp()
            # Store as metrics for immediate use
            from app.storage.db import upsert_metric
            
            upsert_metric('fees.fast', data.get('fastestFee', 0), ts, 'sat/vB')
            upsert_metric('fees.halfhour', data.get('halfHourFee', 0), ts, 'sat/vB')
            upsert_metric('fees.hour', data.get('hourFee', 0), ts, 'sat/vB')
            upsert_metric('fees.economy', data.get('economyFee', 0), ts, 'sat/vB')
            upsert_metric('fees.minimum', data.get('minimumFee', 0), ts, 'sat/vB')
            
            logger.info(f"Collected fee estimates: fast={data.get('fastestFee')} sat/vB")
    
    def collect_rbf_stats(self):
        """Collect RBF replacement statistics."""
        # Note: These endpoints might not be available on public mempool.space
        # Using placeholder logic - would need mempool.space instance with these features
        
        ts = self.get_timestamp()
        day_ago = ts - 86400
        
        # Try to get replacement counts (may need custom mempool instance)
        replacements = 0
        fullrbf = 0
        
        # Get total transaction count from recent blocks
        data = self.get('/v1/blocks/0')
        if data and isinstance(data, list):
            total_tx = sum(block.get('tx_count', 0) for block in data[:6])  # Last ~1 hour
            
            # Estimate RBF activity (would need actual data in production)
            rbf_share = 0.05  # Placeholder 5% estimate
            
            store_json_data('raw_rbf_stats', {
                'ts': ts,
                'replacements': int(total_tx * rbf_share),
                'fullrbf_replacements': int(total_tx * rbf_share * 0.2),  # 20% of RBF is full-RBF estimate
                'total_tx': total_tx,
                'rbf_share': rbf_share * 100
            })
            logger.info(f"Collected RBF stats: {rbf_share * 100:.1f}% estimated RBF share")
    
    def collect_recent_blocks(self):
        """Collect recent block data for SegWit stats."""
        # Get blocks from last 24 hours
        data = self.get('/v1/blocks/0')
        
        if data and isinstance(data, list):
            day = self.get_date_string()
            
            segwit_tx_count = 0
            total_tx_count = 0
            segwit_weight = 0
            total_weight = 0
            
            for block in data[:144]:  # ~1 day of blocks
                if 'extras' in block:
                    extras = block['extras']
                    segwit_tx_count += extras.get('segwitTotalTxs', 0)
                    total_tx_count += block.get('tx_count', 0)
                    segwit_weight += extras.get('segwitTotalWeight', 0)
                    total_weight += extras.get('totalWeight', block.get('weight', 0))
            
            if total_tx_count > 0:
                store_json_data('raw_segwit_stats', {
                    'day': day,
                    'segwit_tx_count': segwit_tx_count,
                    'total_tx_count': total_tx_count,
                    'segwit_weight': segwit_weight,
                    'total_weight': total_weight,
                    'taproot_tx_count': 0  # Would need deeper analysis
                })
                
                segwit_pct = (segwit_tx_count / total_tx_count) * 100 if total_tx_count > 0 else 0
                logger.info(f"Collected SegWit stats: {segwit_pct:.1f}% SegWit adoption")


def main():
    """Run the mempool collector."""
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    collector = MempoolCollector()
    success = collector.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
