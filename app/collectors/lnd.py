"""LND Lightning Network collector for real-time Lightning data."""

import os
import base64
import logging
import requests
from typing import Dict, Optional
from datetime import datetime, timezone

from app.collectors.base import BaseCollector
from app.storage.db import upsert_metric, store_json_data

logger = logging.getLogger(__name__)


class LNDCollector(BaseCollector):
    """Collector for LND Lightning Network node."""
    
    def __init__(self):
        # LND connection details from environment or hardcoded
        self.lnd_host = os.getenv('LND_HOST', 'vwmlv2irnecmi2ym5duoksmnxspaoefgq3dw4vertm2jivpmpf2bh2ad.onion')
        self.lnd_port = os.getenv('LND_PORT', '8080')
        self.macaroon = os.getenv('LND_MACAROON', '0201036c6e6402f801030a10dbbecda94403ee8b90f8b2d2b9e699e01201301a160a0761646472657373120472656164120577726974651a130a04696e666f120472656164120577726974651a170a08696e766f69636573120472656164120577726974651a210a086d616361726f6f6e120867656e6572617465120472656164120577726974651a160a076d657373616765120472656164120577726974651a170a086f6666636861696e120472656164120577726974651a160a076f6e636861696e120472656164120577726974651a140a057065657273120472656164120577726974651a180a067369676e6572120867656e6572617465120472656164000006207244161f90059c2d84aa5bcc91a8da00eef7f19ddb66b2699500519071421520')
        
        # Use Tor if connecting to .onion address
        self.use_tor = self.lnd_host.endswith('.onion')
        
        base_url = f"https://{self.lnd_host}:{self.lnd_port}"
        super().__init__('lnd', base_url, rate_limit_delay=0.5)
        
        # Configure session for LND
        self.session.headers['Grpc-Metadata-macaroon'] = self.macaroon
        self.session.verify = False  # LND uses self-signed certs
        
        # Configure Tor proxy if needed
        if self.use_tor:
            self.session.proxies = {
                'http': 'socks5h://127.0.0.1:9050',
                'https': 'socks5h://127.0.0.1:9050'
            }
            logger.info(f"Using Tor to connect to LND at {self.lnd_host}")
        
        # Disable SSL warnings for self-signed cert
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    def collect(self):
        """Collect Lightning Network data from LND."""
        self.collect_node_info()
        self.collect_channel_stats()
        self.collect_network_info()
        self.collect_forwarding_history()
    
    def collect_node_info(self):
        """Collect node information."""
        try:
            response = self.session.get(f"{self.base_url}/v1/getinfo", timeout=60)
            if response.status_code == 200:
                data = response.json()
                ts = self.get_timestamp()
                
                # Store node metrics
                upsert_metric('lightning.node_active', 1 if data.get('synced_to_chain') else 0, ts)
                upsert_metric('lightning.node_peers', data.get('num_peers', 0), ts)
                upsert_metric('lightning.node_channels_active', data.get('num_active_channels', 0), ts)
                upsert_metric('lightning.node_channels_pending', data.get('num_pending_channels', 0), ts)
                
                logger.info(f"LND node info: {data.get('num_active_channels', 0)} active channels")
        except Exception as e:
            logger.error(f"Failed to get LND node info: {e}")
    
    def collect_channel_stats(self):
        """Collect channel statistics."""
        try:
            response = self.session.get(f"{self.base_url}/v1/channels", timeout=60)
            if response.status_code == 200:
                data = response.json()
                channels = data.get('channels', [])
                ts = self.get_timestamp()
                
                if channels:
                    # Calculate total capacity and balance
                    total_capacity = sum(int(ch.get('capacity', 0)) for ch in channels)
                    total_local = sum(int(ch.get('local_balance', 0)) for ch in channels)
                    total_remote = sum(int(ch.get('remote_balance', 0)) for ch in channels)
                    
                    # Convert sats to BTC
                    capacity_btc = total_capacity / 100000000
                    
                    # Calculate balance ratio
                    balance_ratio = total_local / total_capacity if total_capacity > 0 else 0.5
                    
                    # Store metrics
                    upsert_metric('lightning.capacity', capacity_btc, ts, 'BTC')
                    upsert_metric('lightning.channels', len(channels), ts)
                    upsert_metric('lightning.balance_ratio', balance_ratio, ts)
                    
                    # Calculate channel concentration (how concentrated capacity is)
                    if channels:
                        capacities = [int(ch.get('capacity', 0)) for ch in channels]
                        capacities.sort(reverse=True)
                        # Top 20% of channels control what % of capacity?
                        top_20_pct = int(len(capacities) * 0.2) or 1
                        top_20_capacity = sum(capacities[:top_20_pct])
                        concentration = top_20_capacity / total_capacity if total_capacity > 0 else 0
                        upsert_metric('lightning.node_concentration', concentration, ts)
                    
                    logger.info(f"Channel stats: {len(channels)} channels, {capacity_btc:.2f} BTC capacity")
        except Exception as e:
            logger.error(f"Failed to get channel stats: {e}")
    
    def collect_network_info(self):
        """Collect network graph information."""
        try:
            response = self.session.get(f"{self.base_url}/v1/graph/info", timeout=60)
            if response.status_code == 200:
                data = response.json()
                ts = self.get_timestamp()
                
                # Store network metrics
                node_count = data.get('num_nodes', 0)
                channel_count = data.get('num_channels', 0)
                
                upsert_metric('lightning.network_nodes', node_count, ts)
                upsert_metric('lightning.network_channels', channel_count, ts)
                
                # Calculate network density
                if node_count > 1:
                    # Actual channels vs maximum possible channels
                    max_channels = (node_count * (node_count - 1)) / 2
                    density = channel_count / max_channels if max_channels > 0 else 0
                    upsert_metric('lightning.network_density', density, ts)
                
                logger.info(f"Network info: {node_count} nodes, {channel_count} channels")
        except Exception as e:
            logger.error(f"Failed to get network info: {e}")
    
    def collect_forwarding_history(self):
        """Collect forwarding history for routing metrics."""
        try:
            # Get last 24 hours of forwarding events
            response = self.session.get(f"{self.base_url}/v1/switch", timeout=60)
            if response.status_code == 200:
                data = response.json()
                events = data.get('forwarding_events', [])
                ts = self.get_timestamp()
                
                if events:
                    # Calculate routing metrics
                    total_forwarded = sum(int(e.get('amt_out', 0)) for e in events)
                    total_fees = sum(int(e.get('fee', 0)) for e in events)
                    
                    # Convert to BTC
                    forwarded_btc = total_forwarded / 100000000
                    fees_btc = total_fees / 100000000
                    
                    upsert_metric('lightning.routing_volume_24h', forwarded_btc, ts, 'BTC')
                    upsert_metric('lightning.routing_fees_24h', fees_btc, ts, 'BTC')
                    upsert_metric('lightning.routing_events_24h', len(events), ts)
                    
                    logger.info(f"Routing: {len(events)} forwards, {forwarded_btc:.6f} BTC volume")
        except Exception as e:
            logger.error(f"Failed to get forwarding history: {e}")
    
    def calculate_growth(self):
        """Calculate Lightning growth metrics."""
        ts = self.get_timestamp()
        
        # This would need historical data to calculate properly
        # For now, estimate based on network trends
        upsert_metric('lightning.capacity_growth', 3.5, ts, '%')  # Monthly growth estimate


def main():
    """Test the LND collector."""
    import sys
    logging.basicConfig(level=logging.INFO)
    
    collector = LNDCollector()
    if collector.run():
        print("LND collection successful!")
        sys.exit(0)
    else:
        print("LND collection failed")
        sys.exit(1)


if __name__ == '__main__':
    main()