"""Blockchain.com Charts API collector for UTXO and other chain metrics."""

import os
import logging
from typing import Dict
from datetime import datetime, timedelta

from app.collectors.base import BaseCollector
from app.storage.db import store_json_data, upsert_metric

logger = logging.getLogger(__name__)


class BlockchainChartsCollector(BaseCollector):
    """Collector for Blockchain.com Charts API data."""
    
    def __init__(self):
        base_url = os.getenv('BLOCKCHAIN_API_BASE', 'https://api.blockchain.info')
        super().__init__('blockchain_charts', base_url, rate_limit_delay=1.0)
    
    def collect(self):
        """Collect all Blockchain.com chart data."""
        self.collect_utxo_count()
        self.collect_additional_metrics()
    
    def collect_utxo_count(self):
        """Collect UTXO set size data."""
        # Get UTXO count for last 2 years
        data = self.get('/charts/utxo-count', params={
            'timespan': '2years',
            'format': 'json',
            'sampled': 'false'
        })
        
        if data and 'values' in data:
            values = data['values']
            if len(values) > 0:
                # Get latest value
                latest = values[-1]
                day = self.get_date_string()
                current_utxos = latest.get('y', 0)
                
                # Calculate changes
                change_24h = 0
                change_7d = 0
                
                # Find 24h ago value
                day_ago_ts = self.get_timestamp() - 86400
                for val in reversed(values):
                    if val.get('x', 0) <= day_ago_ts:
                        prev_utxos = val.get('y', 0)
                        if prev_utxos > 0:
                            change_24h = ((current_utxos - prev_utxos) / prev_utxos) * 100
                        break
                
                # Find 7d ago value
                week_ago_ts = self.get_timestamp() - (7 * 86400)
                for val in reversed(values):
                    if val.get('x', 0) <= week_ago_ts:
                        prev_utxos = val.get('y', 0)
                        if prev_utxos > 0:
                            change_7d = ((current_utxos - prev_utxos) / prev_utxos) * 100
                        break
                
                # Store raw data
                store_json_data('raw_utxo_count', {
                    'day': day,
                    'utxos': current_utxos,
                    'change_24h': change_24h,
                    'change_7d': change_7d
                })
                
                # Store as metrics
                ts = self.get_timestamp()
                upsert_metric('adoption.utxo_count', current_utxos, ts)
                upsert_metric('adoption.utxo_growth_24h', change_24h, ts, '%')
                upsert_metric('adoption.utxo_growth_7d', change_7d, ts, '%')
                
                logger.info(f"Collected UTXO count: {current_utxos:,} (24h: {change_24h:+.2f}%, 7d: {change_7d:+.2f}%)")
    
    def collect_additional_metrics(self):
        """Collect other useful blockchain metrics."""
        metrics_to_collect = [
            ('n-transactions', 'chain.tx_count'),
            ('blocks-size', 'chain.block_size'),
            ('hash-rate', 'security.hashrate'),
            ('difficulty', 'security.difficulty'),
            ('miners-revenue', 'security.miner_revenue'),
            ('transaction-fees', 'fees.total_daily'),
            ('mempool-size', 'throughput.mempool_bytes'),
            ('avg-block-size', 'chain.avg_block_size'),
            ('n-unique-addresses', 'adoption.unique_addresses'),
            ('n-transactions-per-block', 'throughput.tx_per_block')
        ]
        
        for chart_name, metric_name in metrics_to_collect:
            try:
                data = self.get(f'/charts/{chart_name}', params={
                    'timespan': '30days',
                    'format': 'json',
                    'sampled': 'false'
                })
                
                if data and 'values' in data:
                    values = data['values']
                    if len(values) > 0:
                        latest = values[-1]
                        value = latest.get('y', 0)
                        ts = self.get_timestamp()
                        
                        upsert_metric(metric_name, value, ts)
                        logger.debug(f"Collected {chart_name}: {value}")
            
            except Exception as e:
                logger.warning(f"Failed to collect {chart_name}: {e}")
                continue


def main():
    """Run the Blockchain.com Charts collector."""
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    collector = BlockchainChartsCollector()
    success = collector.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
