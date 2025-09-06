"""CoinGecko data collector for Bitcoin price data."""

import os
import logging
from typing import Dict

from app.collectors.base import BaseCollector
from app.storage.db import store_json_data, upsert_metric

logger = logging.getLogger(__name__)


class CoinGeckoCollector(BaseCollector):
    """Collector for CoinGecko API data."""
    
    def __init__(self):
        base_url = os.getenv('COINGECKO_API_BASE', 'https://api.coingecko.com/api/v3')
        super().__init__('coingecko', base_url, rate_limit_delay=1.0)
    
    def collect(self):
        """Collect Bitcoin price data."""
        self.collect_price_data()
    
    def collect_price_data(self):
        """Collect current Bitcoin price and market data."""
        # Get simple price
        data = self.get('/simple/price', params={
            'ids': 'bitcoin',
            'vs_currencies': 'usd',
            'include_market_cap': 'true',
            'include_24hr_vol': 'true',
            'include_24hr_change': 'true'
        })
        
        if data and 'bitcoin' in data:
            btc_data = data['bitcoin']
            ts = self.get_timestamp()
            
            # Store raw price data
            store_json_data('raw_price', {
                'ts': ts,
                'price_usd': btc_data.get('usd', 0),
                'volume_24h': btc_data.get('usd_24h_vol', 0),
                'market_cap': btc_data.get('usd_market_cap', 0)
            })
            
            # Store as metric for immediate use
            price = btc_data.get('usd', 0)
            upsert_metric('price.btc_usd', price, ts, 'USD')
            
            logger.info(f"Collected BTC price: ${price:,.2f} USD")
        
        # Get more detailed market data if needed
        self.collect_market_chart()
    
    def collect_market_chart(self):
        """Collect historical price data for trend analysis."""
        # Get 24h price data for volatility calculations
        data = self.get('/coins/bitcoin/market_chart', params={
            'vs_currency': 'usd',
            'days': '1',
            'interval': 'hourly'
        })
        
        if data and 'prices' in data:
            prices = data['prices']
            if len(prices) > 0:
                # Calculate 24h volatility
                price_values = [p[1] for p in prices]
                if len(price_values) > 1:
                    import numpy as np
                    volatility = np.std(price_values) / np.mean(price_values)
                    
                    ts = self.get_timestamp()
                    upsert_metric('price.volatility_24h', volatility, ts)
                    
                    logger.info(f"Calculated 24h volatility: {volatility:.4f}")


def main():
    """Run the CoinGecko collector."""
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    collector = CoinGeckoCollector()
    success = collector.run()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
