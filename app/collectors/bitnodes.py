"""Bitnodes data collector for node network statistics."""

import os
import json
import logging
from collections import Counter
from typing import Dict, List

from app.collectors.base import BaseCollector
from app.storage.db import store_json_data

logger = logging.getLogger(__name__)


class BitnodesCollector(BaseCollector):
    """Collector for Bitnodes API data."""
    
    def __init__(self):
        base_url = os.getenv('BITNODES_API_BASE', 'https://bitnodes.io/api/v1')
        # Bitnodes has strict rate limits: 50 requests/day without API key
        # So we use a longer delay and collect less frequently
        super().__init__('bitnodes', base_url, rate_limit_delay=2.0)
    
    def collect(self):
        """Collect all Bitnodes data."""
        self.collect_network_snapshot()
    
    def collect_network_snapshot(self):
        """Collect network node statistics."""
        # Get latest snapshot
        snapshot_data = self.get('/snapshots/latest/')
        
        if not snapshot_data:
            logger.warning("Failed to get Bitnodes snapshot")
            return
        
        # Parse node data
        nodes = snapshot_data.get('nodes', {})
        total_nodes = len(nodes)
        
        # Count ASNs
        asn_counts = Counter()
        tor_nodes = 0
        country_counts = Counter()
        
        for node_info in nodes.values():
            if isinstance(node_info, list) and len(node_info) >= 7:
                # node_info format: [protocol, user_agent, connected_since, services, height, hostname, city, country, ...]
                asn = node_info[9] if len(node_info) > 9 else 'Unknown'
                country = node_info[7] if len(node_info) > 7 else 'Unknown'
                
                if asn == 'TOR' or 'onion' in str(node_info[5]).lower():
                    tor_nodes += 1
                    asn_counts['TOR'] += 1
                else:
                    asn_counts[asn] += 1
                
                country_counts[country] += 1
        
        # Extract user agents from nodes data
        user_agents = Counter()
        for node_info in nodes.values():
            if isinstance(node_info, list) and len(node_info) >= 2:
                user_agent = node_info[1] if node_info[1] else 'Unknown'
                # Simplify user agent to major version
                if '/' in user_agent:
                    parts = user_agent.split('/')
                    if len(parts) >= 2:
                        version_parts = parts[1].split('.')
                        if len(version_parts) >= 2:
                            user_agent = f"{parts[0]}/{version_parts[0]}.{version_parts[1]}"
                user_agents[user_agent] += 1
        
        # Store the data
        store_json_data('raw_bitnodes_snapshot', {
            'ts': self.get_timestamp(),
            'total_nodes': total_nodes,
            'user_agents': dict(user_agents),  # Convert to dict for JSON storage
            'asn_counts': dict(asn_counts.most_common(100)),  # Top 100 ASNs
            'tor_nodes': tor_nodes,
            'countries': dict(country_counts.most_common(50))  # Top 50 countries
        })
        
        logger.info(f"Collected Bitnodes snapshot: {total_nodes} nodes, {tor_nodes} Tor nodes")
        
        # Calculate and store metrics immediately
        self.calculate_metrics(asn_counts, user_agents, total_nodes, tor_nodes)
    
    def calculate_metrics(self, asn_counts: Counter, user_agents: Dict, 
                         total_nodes: int, tor_nodes: int):
        """Calculate and store network health metrics."""
        from app.storage.db import upsert_metric
        ts = self.get_timestamp()
        
        # Calculate ASN HHI (Herfindahl-Hirschman Index)
        if total_nodes > 0:
            asn_hhi = sum((count / total_nodes) ** 2 for count in asn_counts.values())
            upsert_metric('decent.node_asn_hhi', asn_hhi, ts)
            
            # Top 3 ASN concentration
            top3_asns = sum(count for _, count in asn_counts.most_common(3))
            top3_concentration = top3_asns / total_nodes
            upsert_metric('decent.node_asn_top3', top3_concentration, ts)
            
            # Tor share
            tor_share = tor_nodes / total_nodes
            upsert_metric('decent.tor_share', tor_share, ts)
            
            logger.info(f"ASN HHI: {asn_hhi:.4f}, Top-3 ASN: {top3_concentration:.2%}, Tor: {tor_share:.2%}")
        
        # Calculate client version entropy
        if user_agents:
            total_count = sum(user_agents.values())
            if total_count > 0:
                # Calculate Shannon entropy
                entropy = 0
                for count in user_agents.values():
                    if count > 0:
                        p = count / total_count
                        entropy -= p * (p if p == 0 else p * (1 if p == 1 else -1 * (p * (1 / p)).bit_length() / 8))
                
                # Normalize by maximum possible entropy
                max_entropy = (len(user_agents)).bit_length() / 8 if len(user_agents) > 1 else 1
                normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0
                
                upsert_metric('decent.client_entropy', normalized_entropy, ts)
                logger.info(f"Client entropy: {normalized_entropy:.4f}")


def main():
    """Run the Bitnodes collector."""
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    collector = BitnodesCollector()
    success = collector.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
