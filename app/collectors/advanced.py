"""Advanced collectors for Phase 2 features - UTXO analysis, orphan detection, Lightning topology."""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from collections import Counter
import numpy as np

from app.collectors.base import BaseCollector
from app.storage.db import store_json_data, execute_insert, upsert_metric

logger = logging.getLogger(__name__)


class UTXOAnalyzer(BaseCollector):
    """Analyze UTXO distribution for dust and inscription detection."""
    
    def __init__(self):
        base_url = os.getenv('MEMPOOL_API_BASE', 'https://mempool.space/api')
        super().__init__('utxo_analyzer', base_url, rate_limit_delay=1.0)
    
    def collect(self):
        """Collect UTXO distribution data."""
        self.analyze_utxo_distribution()
        self.detect_inscriptions()
    
    def analyze_utxo_distribution(self):
        """Analyze UTXO set distribution."""
        # Note: Full UTXO analysis requires a full node or specialized service
        # This is a simplified version using available APIs
        
        # Define UTXO value bands (in satoshis)
        bands = [
            (0, 546),           # Dust (below dust limit)
            (546, 1000),        # Near-dust
            (1000, 10000),      # Small
            (10000, 100000),    # Medium-small
            (100000, 1000000),  # Medium
            (1000000, 10000000), # Medium-large
            (10000000, 100000000), # Large (0.1-1 BTC)
            (100000000, float('inf')) # Very large (>1 BTC)
        ]
        
        # Get recent blocks to sample UTXO creation
        blocks_data = self.get('/v1/blocks/0')
        
        if blocks_data and isinstance(blocks_data, list):
            utxo_samples = []
            
            for block in blocks_data[:10]:  # Sample last 10 blocks
                # Get block transactions
                block_hash = block.get('id')
                if block_hash:
                    txs_data = self.get(f'/v1/block/{block_hash}/txs')
                    if txs_data:
                        for tx in txs_data[:100]:  # Sample first 100 txs
                            for vout in tx.get('vout', []):
                                value = vout.get('value', 0)
                                utxo_samples.append(value)
            
            if utxo_samples:
                # Calculate distribution
                distribution = Counter()
                dust_count = 0
                total_value = 0
                
                for value in utxo_samples:
                    total_value += value
                    for i, (min_val, max_val) in enumerate(bands):
                        if min_val <= value < max_val:
                            distribution[f'band_{i}'] += 1
                            if value < 546:  # Dust threshold
                                dust_count += 1
                            break
                
                # Calculate metrics
                ts = self.get_timestamp()
                dust_ratio = dust_count / len(utxo_samples) if utxo_samples else 0
                
                upsert_metric('adoption.dust_ratio', dust_ratio, ts)
                upsert_metric('adoption.utxo_sample_size', len(utxo_samples), ts)
                
                # Store distribution
                store_json_data('raw_utxo_distribution', {
                    'ts': ts,
                    'distribution': dict(distribution),
                    'dust_count': dust_count,
                    'total_samples': len(utxo_samples),
                    'avg_value': total_value / len(utxo_samples) if utxo_samples else 0
                })
                
                logger.info(f"UTXO distribution: {dust_ratio:.2%} dust, {len(utxo_samples)} samples")
    
    def detect_inscriptions(self):
        """Detect inscription-related transactions."""
        # Inscriptions typically use OP_FALSE OP_IF patterns
        # This is a simplified detection based on transaction patterns
        
        blocks_data = self.get('/v1/blocks/0')
        
        if blocks_data and isinstance(blocks_data, list):
            inscription_count = 0
            total_tx_count = 0
            
            for block in blocks_data[:5]:  # Check last 5 blocks
                block_hash = block.get('id')
                if block_hash:
                    txs_data = self.get(f'/v1/block/{block_hash}/txs')
                    if txs_data:
                        for tx in txs_data:
                            total_tx_count += 1
                            # Check for inscription patterns
                            # Simplified: look for witness data size
                            if 'witness' in str(tx).lower():
                                for vin in tx.get('vin', []):
                                    witness = vin.get('witness', [])
                                    if witness and len(witness) > 2:
                                        # Large witness data might indicate inscription
                                        witness_size = sum(len(str(w)) for w in witness)
                                        if witness_size > 1000:  # Arbitrary threshold
                                            inscription_count += 1
                                            break
            
            if total_tx_count > 0:
                inscription_ratio = inscription_count / total_tx_count
                ts = self.get_timestamp()
                upsert_metric('adoption.inscription_ratio', inscription_ratio, ts)
                
                logger.info(f"Inscription detection: {inscription_ratio:.2%} of {total_tx_count} transactions")


class OrphanDetector(BaseCollector):
    """Detect orphaned blocks and analyze per-pool statistics."""
    
    def __init__(self):
        base_url = os.getenv('MEMPOOL_API_BASE', 'https://mempool.space/api')
        super().__init__('orphan_detector', base_url, rate_limit_delay=1.0)
        self.known_blocks = {}  # Cache of known blocks
    
    def collect(self):
        """Collect orphan block data."""
        self.detect_orphans()
        self.analyze_pool_orphans()
    
    def detect_orphans(self):
        """Detect potential orphaned blocks."""
        # Get recent blocks
        blocks = self.get('/v1/blocks/0')
        
        if not blocks:
            return
        
        orphan_candidates = []
        ts = self.get_timestamp()
        
        # Check for height conflicts (same height, different hash)
        height_map = {}
        for block in blocks:
            height = block.get('height')
            block_hash = block.get('id')
            
            if height in height_map:
                # Potential orphan detected
                if height_map[height] != block_hash:
                    orphan_candidates.append({
                        'height': height,
                        'hash1': height_map[height],
                        'hash2': block_hash,
                        'timestamp': block.get('timestamp')
                    })
            else:
                height_map[height] = block_hash
        
        if orphan_candidates:
            store_json_data('raw_orphan_candidates', {
                'ts': ts,
                'candidates': orphan_candidates,
                'count': len(orphan_candidates)
            })
            
            logger.info(f"Detected {len(orphan_candidates)} potential orphan blocks")
        
        # Update metrics
        upsert_metric('security.orphan_rate', len(orphan_candidates) / len(blocks) if blocks else 0, ts)
    
    def analyze_pool_orphans(self):
        """Analyze orphan rates by mining pool."""
        # Get pool statistics
        pools_data = self.get('/v1/mining/pools/1d')
        
        if not pools_data or 'pools' not in pools_data:
            return
        
        ts = self.get_timestamp()
        pool_orphan_stats = {}
        
        for pool in pools_data['pools']:
            pool_name = pool.get('name', 'Unknown')
            blocks_found = pool.get('blockCount', 0)
            
            # In production, you'd cross-reference with orphan detection
            # Here we estimate based on statistical models
            expected_orphan_rate = 0.001  # ~0.1% baseline orphan rate
            
            # Larger pools might have slightly different rates
            if blocks_found > 100:
                expected_orphan_rate *= 0.9  # Better connected
            elif blocks_found < 10:
                expected_orphan_rate *= 1.2  # Potentially less connected
            
            pool_orphan_stats[pool_name] = {
                'blocks': blocks_found,
                'expected_orphans': blocks_found * expected_orphan_rate,
                'orphan_rate': expected_orphan_rate
            }
        
        # Store pool orphan statistics
        store_json_data('raw_pool_orphan_stats', {
            'ts': ts,
            'pools': pool_orphan_stats
        })
        
        # Calculate weighted average orphan rate
        total_blocks = sum(p['blocks'] for p in pool_orphan_stats.values())
        weighted_orphan_rate = sum(
            p['blocks'] * p['orphan_rate'] for p in pool_orphan_stats.values()
        ) / total_blocks if total_blocks > 0 else 0
        
        upsert_metric('security.weighted_orphan_rate', weighted_orphan_rate, ts)
        
        logger.info(f"Pool orphan analysis: {weighted_orphan_rate:.4%} weighted average rate")


class LightningTopologyAnalyzer(BaseCollector):
    """Analyze Lightning Network topology and centrality metrics."""
    
    def __init__(self):
        base_url = os.getenv('MEMPOOL_API_BASE', 'https://mempool.space/api')
        super().__init__('lightning_topology', base_url, rate_limit_delay=1.0)
    
    def collect(self):
        """Collect Lightning Network topology data."""
        self.analyze_node_centrality()
        self.calculate_network_metrics()
    
    def analyze_node_centrality(self):
        """Analyze node centrality and concentration."""
        # Get top Lightning nodes
        nodes_data = self.get('/v1/lightning/nodes/rankings/liquidity')
        
        if not nodes_data:
            return
        
        ts = self.get_timestamp()
        
        # Calculate concentration metrics
        total_capacity = sum(node.get('capacity', 0) for node in nodes_data)
        
        if total_capacity > 0:
            # Calculate Gini coefficient
            capacities = sorted([node.get('capacity', 0) for node in nodes_data])
            n = len(capacities)
            cumsum = np.cumsum(capacities)
            gini = (2 * np.sum((np.arange(1, n+1) * capacities))) / (n * cumsum[-1]) - (n + 1) / n
            
            # Calculate HHI for top nodes
            top_10_capacity = sum(node.get('capacity', 0) for node in nodes_data[:10])
            top_10_share = top_10_capacity / total_capacity
            
            # Calculate centrality scores
            centrality_scores = []
            for node in nodes_data[:50]:  # Top 50 nodes
                capacity = node.get('capacity', 0)
                channels = node.get('channels', 0)
                
                # Simple centrality score based on capacity and connectivity
                centrality = (capacity / total_capacity) * (channels / 1000)  # Normalize channels
                centrality_scores.append(centrality)
            
            # Store metrics
            upsert_metric('lightning.gini_coefficient', gini, ts)
            upsert_metric('lightning.top10_share', top_10_share, ts)
            upsert_metric('lightning.avg_centrality', np.mean(centrality_scores), ts)
            
            # Store detailed topology data
            store_json_data('raw_lightning_topology', {
                'ts': ts,
                'gini': gini,
                'top10_share': top_10_share,
                'node_count': len(nodes_data),
                'total_capacity': total_capacity,
                'centrality_scores': centrality_scores[:20]  # Store top 20
            })
            
            logger.info(f"Lightning topology: Gini={gini:.3f}, Top-10={top_10_share:.2%}")
    
    def calculate_network_metrics(self):
        """Calculate advanced Lightning Network metrics."""
        # Get network statistics
        stats = self.get('/v1/lightning/statistics/latest')
        
        if not stats:
            return
        
        ts = self.get_timestamp()
        
        # Calculate network density
        node_count = stats.get('node_count', 0)
        channel_count = stats.get('channel_count', 0)
        
        if node_count > 1:
            # Maximum possible channels in a fully connected network
            max_channels = (node_count * (node_count - 1)) / 2
            network_density = channel_count / max_channels if max_channels > 0 else 0
            
            # Average degree (channels per node)
            avg_degree = (2 * channel_count) / node_count  # Each channel connects 2 nodes
            
            # Store metrics
            upsert_metric('lightning.network_density', network_density, ts)
            upsert_metric('lightning.avg_degree', avg_degree, ts)
            
            logger.info(f"Lightning metrics: density={network_density:.6f}, avg_degree={avg_degree:.2f}")


class MempoolAnalyzer(BaseCollector):
    """Advanced mempool analysis for fee market dynamics."""
    
    def __init__(self):
        base_url = os.getenv('MEMPOOL_API_BASE', 'https://mempool.space/api')
        super().__init__('mempool_analyzer', base_url, rate_limit_delay=0.5)
    
    def collect(self):
        """Collect advanced mempool metrics."""
        self.analyze_fee_distribution()
        self.detect_fee_spikes()
    
    def analyze_fee_distribution(self):
        """Analyze fee rate distribution in mempool."""
        mempool_data = self.get('/v1/mempool')
        
        if not mempool_data:
            return
        
        ts = self.get_timestamp()
        
        # Get fee histogram if available
        fee_histogram = mempool_data.get('fee_histogram', [])
        
        if fee_histogram:
            # Calculate fee percentiles
            total_size = sum(item[1] for item in fee_histogram)
            
            if total_size > 0:
                cumulative = 0
                percentiles = {}
                targets = [10, 25, 50, 75, 90, 95, 99]
                target_idx = 0
                
                for fee_rate, size in sorted(fee_histogram):
                    cumulative += size
                    percentage = (cumulative / total_size) * 100
                    
                    while target_idx < len(targets) and percentage >= targets[target_idx]:
                        percentiles[f'p{targets[target_idx]}'] = fee_rate
                        target_idx += 1
                
                # Store percentiles
                for key, value in percentiles.items():
                    upsert_metric(f'fees.mempool_{key}', value, ts, 'sat/vB')
                
                # Calculate fee variance
                fees = []
                for fee_rate, size in fee_histogram:
                    fees.extend([fee_rate] * int(size / 1000))  # Sample
                
                if fees:
                    fee_variance = np.var(fees)
                    fee_std = np.std(fees)
                    
                    upsert_metric('fees.variance', fee_variance, ts)
                    upsert_metric('fees.std_dev', fee_std, ts)
                    
                    logger.info(f"Fee distribution: std={fee_std:.2f} sat/vB, p50={percentiles.get('p50', 0)} sat/vB")
    
    def detect_fee_spikes(self):
        """Detect and analyze fee spikes."""
        # Get recent fee recommendations
        fees = self.get('/v1/fees/recommended')
        
        if not fees:
            return
        
        ts = self.get_timestamp()
        fast_fee = fees.get('fastestFee', 0)
        
        # Get historical average (would need to query from database)
        # For now, use a threshold approach
        spike_threshold = 50  # sat/vB
        
        if fast_fee > spike_threshold:
            # Fee spike detected
            spike_ratio = fast_fee / spike_threshold
            
            upsert_metric('fees.spike_detected', 1, ts)
            upsert_metric('fees.spike_ratio', spike_ratio, ts)
            
            logger.info(f"Fee spike detected: {fast_fee} sat/vB ({spike_ratio:.1f}x normal)")
        else:
            upsert_metric('fees.spike_detected', 0, ts)


def main():
    """Run advanced collectors."""
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    collectors = [
        UTXOAnalyzer(),
        OrphanDetector(),
        LightningTopologyAnalyzer(),
        MempoolAnalyzer()
    ]
    
    for collector in collectors:
        logger.info(f"Running {collector.name}...")
        success = collector.run()
        if not success:
            logger.warning(f"{collector.name} failed")
    
    sys.exit(0)


if __name__ == '__main__':
    main()
