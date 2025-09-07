"""Bitcoin Core RPC collector for local node data."""

import os
import json
import logging
import requests
from typing import Dict, Optional
from datetime import datetime, timezone

from app.collectors.base import BaseCollector
from app.storage.db import store_json_data, upsert_metric

logger = logging.getLogger(__name__)


class BitcoinCoreCollector(BaseCollector):
    """Collector for Bitcoin Core node via RPC."""
    
    def __init__(self):
        # Try to get RPC credentials from environment
        self.rpc_user = os.getenv('BITCOIN_RPC_USER', '')
        self.rpc_pass = os.getenv('BITCOIN_RPC_PASS', '')
        self.rpc_host = os.getenv('BITCOIN_RPC_HOST', 'localhost')
        self.rpc_port = os.getenv('BITCOIN_RPC_PORT', '8332')
        
        # Check for cookie auth file (alternative to user/pass)
        self.cookie_path = os.path.expanduser('~/.bitcoin/.cookie')
        
        # Check if host is a Tor onion address
        self.use_tor = self.rpc_host.endswith('.onion')
        
        base_url = f"http://{self.rpc_host}:{self.rpc_port}"
        super().__init__('bitcoin_core', base_url, rate_limit_delay=0.1)
        
        # Configure Tor proxy if needed
        if self.use_tor:
            logger.info(f"Detected Tor onion address: {self.rpc_host}")
            self.session.proxies = {
                'http': 'socks5h://127.0.0.1:9050',
                'https': 'socks5h://127.0.0.1:9050'
            }
            logger.info("Configured SOCKS proxy for Tor connection")
        
        # Set up authentication
        if os.path.exists(self.cookie_path) and not self.use_tor:
            with open(self.cookie_path, 'r') as f:
                auth = f.read().strip().split(':')
                self.session.auth = (auth[0], auth[1])
                logger.info("Using Bitcoin Core cookie authentication")
        elif self.rpc_user and self.rpc_pass:
            self.session.auth = (self.rpc_user, self.rpc_pass)
            logger.info("Using Bitcoin Core RPC credentials")
        else:
            logger.warning("No Bitcoin Core authentication configured")
    
    def rpc_call(self, method: str, params: list = None) -> Optional[Dict]:
        """Make an RPC call to Bitcoin Core."""
        payload = {
            'jsonrpc': '2.0',
            'id': 1,
            'method': method,
            'params': params or []
        }
        
        try:
            # Use longer timeout for Tor connections
            timeout = 60 if self.use_tor else 30
            response = self.session.post(
                self.base_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=timeout
            )
            response.raise_for_status()
            result = response.json()
            
            if 'error' in result and result['error']:
                logger.error(f"RPC error: {result['error']}")
                return None
                
            return result.get('result')
            
        except Exception as e:
            logger.error(f"Bitcoin Core RPC failed: {e}")
            return None
    
    def collect(self):
        """Collect data from Bitcoin Core."""
        # Test connection first
        info = self.rpc_call('getblockchaininfo')
        if not info:
            logger.warning("Cannot connect to Bitcoin Core - skipping collection")
            return
        
        self.collect_blockchain_info(info)
        self.collect_mempool_info()
        self.collect_network_info()
        self.collect_mining_info()
        self.collect_fee_estimates()
    
    def collect_blockchain_info(self, info: Dict):
        """Collect blockchain information."""
        ts = self.get_timestamp()
        
        # Store metrics
        if 'blocks' in info:
            upsert_metric('chain.height', info['blocks'], ts)
            
        if 'size_on_disk' in info:
            size_gb = info['size_on_disk'] / (1024**3)
            upsert_metric('chain.size_on_disk', size_gb, ts, 'GB')
            
        if 'verificationprogress' in info:
            progress = info['verificationprogress'] * 100
            upsert_metric('chain.sync_progress', progress, ts, '%')
            
        logger.info(f"Collected blockchain info: height={info.get('blocks')}")
    
    def collect_mempool_info(self):
        """Collect mempool information."""
        info = self.rpc_call('getmempoolinfo')
        if not info:
            return
            
        ts = self.get_timestamp()
        
        # Store raw mempool data
        store_json_data('raw_mempool_snapshot', {
            'ts': ts,
            'count': info.get('size', 0),
            'vsize': info.get('bytes', 0),
            'total_fee': info.get('total_fee', 0) * 1e8 if 'total_fee' in info else 0
        })
        
        # Store metrics
        upsert_metric('throughput.mempool_count', info.get('size', 0), ts)
        upsert_metric('throughput.mempool_bytes', info.get('bytes', 0), ts, 'bytes')
        
        if 'mempoolminfee' in info:
            min_fee_btc = info['mempoolminfee']
            min_fee_sat = min_fee_btc * 1e8
            upsert_metric('fees.mempool_min', min_fee_sat, ts, 'sat/vB')
            
        logger.info(f"Collected mempool: {info.get('size')} txs, {info.get('bytes')} bytes")
    
    def collect_network_info(self):
        """Collect network information."""
        info = self.rpc_call('getnetworkinfo')
        if not info:
            return
            
        peer_info = self.rpc_call('getpeerinfo')
        
        ts = self.get_timestamp()
        
        if info:
            upsert_metric('network.version', info.get('version', 0), ts)
            upsert_metric('network.connections', info.get('connections', 0), ts)
            
        if peer_info:
            upsert_metric('network.peer_count', len(peer_info), ts)
            
            # Calculate peer diversity (unique ASNs)
            asns = set()
            for peer in peer_info:
                if 'mapped_as' in peer and peer['mapped_as']:
                    asns.add(peer['mapped_as'])
            
            if asns:
                upsert_metric('network.unique_asns', len(asns), ts)
                
        logger.info(f"Collected network info: {info.get('connections')} connections")
    
    def collect_mining_info(self):
        """Collect mining information."""
        info = self.rpc_call('getmininginfo')
        if not info:
            return
            
        ts = self.get_timestamp()
        
        if 'difficulty' in info:
            upsert_metric('security.difficulty', info['difficulty'], ts)
            
        if 'networkhashps' in info:
            # Convert to TH/s
            hashrate_th = info['networkhashps'] / 1e12
            upsert_metric('security.hashrate_th', hashrate_th, ts, 'TH/s')
            
        logger.info(f"Collected mining info: difficulty={info.get('difficulty')}")
    
    def collect_fee_estimates(self):
        """Collect fee estimates for different confirmation targets."""
        ts = self.get_timestamp()
        
        # Estimate fees for different confirmation targets
        targets = {
            'fast': 2,      # 2 blocks (~20 min)
            'medium': 6,    # 6 blocks (~1 hour)  
            'slow': 144     # 144 blocks (~1 day)
        }
        
        for name, blocks in targets.items():
            estimate = self.rpc_call('estimatesmartfee', [blocks])
            if estimate and 'feerate' in estimate:
                # Convert BTC/kB to sat/vB
                fee_btc_kb = estimate['feerate']
                fee_sat_vb = (fee_btc_kb * 1e8) / 1000
                upsert_metric(f'fees.{name}', fee_sat_vb, ts, 'sat/vB')
                
        logger.info("Collected fee estimates from Bitcoin Core")


def main():
    """Test the Bitcoin Core collector."""
    import sys
    logging.basicConfig(level=logging.INFO)
    
    collector = BitcoinCoreCollector()
    if collector.run():
        print("Bitcoin Core collection successful!")
        sys.exit(0)
    else:
        print("Bitcoin Core collection failed")
        sys.exit(1)


if __name__ == '__main__':
    main()