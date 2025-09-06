"""ForkMonitor RSS feed collector for stale blocks and reorgs."""

import os
import logging
import feedparser
from datetime import datetime, timezone
from typing import List, Dict

from app.collectors.base import BaseCollector
from app.storage.db import store_json_data, execute_query, upsert_metric

logger = logging.getLogger(__name__)


class ForkMonitorCollector(BaseCollector):
    """Collector for ForkMonitor stale block data."""
    
    def __init__(self):
        base_url = os.getenv('FORKMONITOR_BASE', 'https://forkmonitor.info')
        super().__init__('forkmonitor', base_url, rate_limit_delay=1.0)
    
    def collect(self):
        """Collect stale block incidents from RSS feed."""
        self.collect_stale_blocks()
    
    def collect_stale_blocks(self):
        """Parse RSS feed for stale block incidents."""
        # Get RSS feed
        feed_url = f"{self.base_url}/feeds/stale_candidates/btc.rss"
        
        try:
            feed = feedparser.parse(feed_url)
            
            if feed.bozo:
                logger.warning(f"ForkMonitor RSS feed parse error: {feed.bozo_exception}")
                return
            
            incidents_added = 0
            
            for entry in feed.entries:
                # Parse entry data
                title = entry.get('title', '')
                description = entry.get('description', '')
                published = entry.get('published_parsed')
                
                # Extract block height from title (usually format: "Stale block at height XXXXXX")
                height = None
                if 'height' in title.lower():
                    parts = title.split()
                    for i, part in enumerate(parts):
                        if part.lower() == 'height' and i + 1 < len(parts):
                            try:
                                height = int(parts[i + 1].replace(',', ''))
                            except ValueError:
                                pass
                
                # Extract pool name if mentioned
                pool = 'Unknown'
                common_pools = ['F2Pool', 'AntPool', 'Poolin', 'ViaBTC', 'Binance', 'Slush', 'BTC.com']
                for pool_name in common_pools:
                    if pool_name.lower() in description.lower():
                        pool = pool_name
                        break
                
                # Convert published time to timestamp
                ts = None
                if published:
                    dt = datetime(*published[:6], tzinfo=timezone.utc)
                    ts = int(dt.timestamp())
                else:
                    ts = self.get_timestamp()
                
                # Extract block hash if available
                block_hash = None
                if 'hash' in description.lower():
                    # Try to find hex string that looks like a hash
                    import re
                    hash_pattern = r'[0-9a-fA-F]{64}'
                    matches = re.findall(hash_pattern, description)
                    if matches:
                        block_hash = matches[0]
                
                # Check if we already have this incident
                existing = execute_query(
                    "SELECT * FROM raw_stale_incidents WHERE height = ? AND ts = ?",
                    (height, ts)
                )
                
                if not existing:
                    store_json_data('raw_stale_incidents', {
                        'ts': ts,
                        'height': height,
                        'pool': pool,
                        'hash': block_hash,
                        'description': description[:500]  # Limit description length
                    })
                    incidents_added += 1
            
            logger.info(f"Processed {len(feed.entries)} ForkMonitor entries, added {incidents_added} new incidents")
            
            # Calculate metrics
            self.calculate_stale_metrics()
            
        except Exception as e:
            logger.error(f"Failed to collect ForkMonitor data: {e}")
    
    def calculate_stale_metrics(self):
        """Calculate stale block incidence metrics."""
        ts = self.get_timestamp()
        
        # Count incidents over different time windows
        windows = [
            (30, 'security.stale_30d'),
            (90, 'security.stale_90d'),
            (365, 'security.stale_365d')
        ]
        
        for days, metric_id in windows:
            cutoff = ts - (days * 86400)
            
            incidents = execute_query(
                "SELECT COUNT(*) as count FROM raw_stale_incidents WHERE ts >= ?",
                (cutoff,)
            )
            
            count = incidents[0]['count'] if incidents else 0
            
            # Normalize to incidents per day
            incidents_per_day = count / days
            
            upsert_metric(metric_id, incidents_per_day, ts, 'incidents/day')
            
            logger.info(f"Stale blocks ({days}d): {count} incidents ({incidents_per_day:.4f}/day)")
        
        # Get time since last incident
        last_incident = execute_query(
            "SELECT MAX(ts) as last_ts FROM raw_stale_incidents"
        )
        
        if last_incident and last_incident[0]['last_ts']:
            days_since_last = (ts - last_incident[0]['last_ts']) / 86400
            upsert_metric('security.days_since_stale', days_since_last, ts, 'days')
            logger.info(f"Days since last stale block: {days_since_last:.1f}")


def main():
    """Run the ForkMonitor collector."""
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    collector = ForkMonitorCollector()
    success = collector.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
