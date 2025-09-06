"""Prometheus metrics exporter for Bitcoin Health Scorecard."""

import os
import time
import logging
from typing import Dict
from prometheus_client import start_http_server, Gauge, Counter, Histogram, Info
from prometheus_client.core import CollectorRegistry

from app.storage.db import (
    get_latest_scores, get_latest_metric, execute_query,
    get_meta_config
)

logger = logging.getLogger(__name__)

# Create a custom registry
registry = CollectorRegistry()

# Define Prometheus metrics
# Overall and pillar scores
overall_score = Gauge('btc_health_overall_score', 'Overall Bitcoin network health score (0-100)', registry=registry)
pillar_score = Gauge('btc_health_pillar_score', 'Pillar health scores', ['pillar'], registry=registry)

# Security metrics
hashprice = Gauge('btc_health_hashprice_usd_th_day', 'Mining hashprice in USD/TH/day', registry=registry)
fee_share = Gauge('btc_health_fee_share', 'Fee share of miner revenue', registry=registry)
difficulty_momentum = Gauge('btc_health_difficulty_momentum', 'Difficulty adjustment momentum', registry=registry)
stale_rate = Gauge('btc_health_stale_rate', 'Stale block rate', registry=registry)

# Decentralization metrics
pool_hhi = Gauge('btc_health_pool_hhi', 'Mining pool Herfindahl-Hirschman Index', registry=registry)
node_asn_hhi = Gauge('btc_health_node_asn_hhi', 'Node ASN concentration HHI', registry=registry)
client_entropy = Gauge('btc_health_client_entropy', 'Client version entropy', registry=registry)
tor_share = Gauge('btc_health_tor_share', 'Percentage of Tor nodes', registry=registry)

# Throughput metrics
mempool_vsize = Gauge('btc_health_mempool_vsize', 'Mempool size in vbytes', registry=registry)
fee_elasticity = Gauge('btc_health_fee_elasticity', 'Fee market elasticity correlation', registry=registry)
fees_fast = Gauge('btc_health_fees_fast', 'Fast confirmation fee rate', ['type'], registry=registry)
fees_medium = Gauge('btc_health_fees_medium', 'Medium confirmation fee rate', registry=registry)
fees_slow = Gauge('btc_health_fees_slow', 'Slow confirmation fee rate', registry=registry)

# Adoption metrics
utxo_count = Gauge('btc_health_utxo_count', 'Total UTXO count', registry=registry)
utxo_growth = Gauge('btc_health_utxo_growth', 'UTXO growth rate', registry=registry)
segwit_usage = Gauge('btc_health_segwit_usage', 'SegWit transaction percentage', registry=registry)
rbf_activity = Gauge('btc_health_rbf_activity', 'RBF transaction percentage', registry=registry)

# Lightning metrics
lightning_capacity = Gauge('btc_health_lightning_capacity_btc', 'Lightning Network capacity in BTC', registry=registry)
lightning_channels = Gauge('btc_health_lightning_channels', 'Lightning Network channel count', registry=registry)
lightning_nodes = Gauge('btc_health_lightning_nodes', 'Lightning Network node count', registry=registry)
lightning_growth = Gauge('btc_health_lightning_growth', 'Lightning capacity growth rate', registry=registry)

# Price metrics
btc_price_usd = Gauge('btc_health_price_usd', 'Bitcoin price in USD', registry=registry)
price_volatility = Gauge('btc_health_price_volatility', 'Bitcoin price volatility', registry=registry)

# System metrics
collector_failures = Gauge('btc_health_collector_failures', 'Consecutive collector failures', ['collector'], registry=registry)
last_update = Gauge('btc_health_last_update_timestamp', 'Last data update timestamp', registry=registry)
database_size = Gauge('btc_health_database_size_bytes', 'Database file size in bytes', registry=registry)

# Info metrics
version_info = Info('btc_health_version', 'Version information', registry=registry)


class MetricsExporter:
    """Export metrics to Prometheus format."""
    
    def __init__(self, port: int = 9090):
        """
        Initialize metrics exporter.
        
        Args:
            port: Port to expose metrics on
        """
        self.port = port
        self.running = False
    
    def update_metrics(self):
        """Update all Prometheus metrics from database."""
        try:
            # Update overall score
            overall = execute_query(
                "SELECT score FROM scores WHERE kind='overall' AND id='overall' ORDER BY ts DESC LIMIT 1"
            )
            if overall:
                overall_score.set(overall[0]['score'])
            
            # Update pillar scores
            pillars = execute_query(
                "SELECT id, score FROM scores WHERE kind='pillar' AND ts = (SELECT MAX(ts) FROM scores WHERE kind='pillar')"
            )
            for p in pillars:
                pillar_score.labels(pillar=p['id']).set(p['score'])
            
            # Update individual metrics
            self._update_metric(hashprice, 'security.hashprice')
            self._update_metric(fee_share, 'security.fee_share')
            self._update_metric(difficulty_momentum, 'security.difficulty_momentum')
            self._update_metric(stale_rate, 'security.stale_30d')
            
            self._update_metric(pool_hhi, 'decent.pool_hhi')
            self._update_metric(node_asn_hhi, 'decent.node_asn_hhi')
            self._update_metric(client_entropy, 'decent.client_entropy')
            self._update_metric(tor_share, 'decent.tor_share')
            
            self._update_metric(mempool_vsize, 'throughput.mempool_pressure')
            self._update_metric(fee_elasticity, 'throughput.fee_elasticity')
            
            # Fee rates
            for fee_type in ['fast', 'halfhour', 'hour', 'economy']:
                metric_data = get_latest_metric(f'fees.{fee_type}')
                if metric_data:
                    if fee_type == 'fast':
                        fees_fast.set(metric_data['value'])
                    elif fee_type == 'halfhour':
                        fees_medium.set(metric_data['value'])
                    elif fee_type == 'economy':
                        fees_slow.set(metric_data['value'])
            
            self._update_metric(utxo_count, 'adoption.utxo_count')
            self._update_metric(utxo_growth, 'adoption.utxo_growth_7d')
            self._update_metric(segwit_usage, 'adoption.segwit_usage')
            self._update_metric(rbf_activity, 'adoption.rbf_activity')
            
            self._update_metric(lightning_capacity, 'lightning.capacity_btc')
            self._update_metric(lightning_channels, 'lightning.channels')
            self._update_metric(lightning_nodes, 'lightning.nodes')
            self._update_metric(lightning_growth, 'lightning.capacity_growth')
            
            self._update_metric(btc_price_usd, 'price.btc_usd')
            self._update_metric(price_volatility, 'price.volatility_24h')
            
            # Update collector status
            collectors = execute_query("SELECT * FROM collection_status")
            for c in collectors:
                collector_failures.labels(collector=c['collector']).set(c['consecutive_failures'])
            
            # Update last update timestamp
            last_collection = get_meta_config('last_collection')
            if last_collection:
                from datetime import datetime
                dt = datetime.fromisoformat(last_collection)
                last_update.set(dt.timestamp())
            
            # Update database size
            db_path = os.getenv('DB_PATH', 'btc_health.db')
            if os.path.exists(db_path):
                database_size.set(os.path.getsize(db_path))
            
            # Update version info
            version = get_meta_config('version') or '1.0.0'
            version_info.info({'version': version})
            
            logger.debug("Metrics updated successfully")
            
        except Exception as e:
            logger.error(f"Error updating metrics: {e}")
    
    def _update_metric(self, gauge: Gauge, metric_id: str):
        """Update a single gauge metric."""
        data = get_latest_metric(metric_id)
        if data and data['value'] is not None:
            gauge.set(data['value'])
    
    def start(self):
        """Start the metrics exporter."""
        logger.info(f"Starting Prometheus metrics exporter on port {self.port}")
        
        # Start HTTP server
        start_http_server(self.port, registry=registry)
        self.running = True
        
        # Update metrics loop
        while self.running:
            self.update_metrics()
            time.sleep(30)  # Update every 30 seconds
    
    def stop(self):
        """Stop the metrics exporter."""
        self.running = False
        logger.info("Metrics exporter stopped")


def main():
    """Run the metrics exporter."""
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    port = int(os.getenv('METRICS_PORT', 9090))
    exporter = MetricsExporter(port)
    
    try:
        exporter.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt, shutting down...")
        exporter.stop()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Exporter failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
