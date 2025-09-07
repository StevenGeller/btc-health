"""Binance data collector for Bitcoin price and market data."""

import logging
from typing import Dict, List
from datetime import datetime, timezone, timedelta

from app.collectors.base import BaseCollector
from app.storage.db import store_json_data, upsert_metric

logger = logging.getLogger(__name__)


class BinanceCollector(BaseCollector):
    """Collector for Binance public API data (no authentication required)."""
    
    def __init__(self):
        super().__init__('binance', 'https://api.binance.com', rate_limit_delay=0.5)
    
    def collect(self):
        """Collect Bitcoin price and market data from Binance."""
        self.collect_current_price()
        self.collect_historical_prices()
        self.collect_24hr_stats()
    
    def collect_current_price(self):
        """Collect current BTC/USDT price."""
        data = self.get('/api/v3/ticker/price', params={'symbol': 'BTCUSDT'})
        
        if data and 'price' in data:
            ts = self.get_timestamp()
            price = float(data['price'])
            
            # Store raw price data
            store_json_data('raw_price', {
                'ts': ts,
                'price_usd': price,
                'volume_24h': 0,
                'market_cap': price * 19500000  # Approximate supply
            })
            
            # Store as metric
            upsert_metric('price.btc_usd', price, ts, 'USD')
            
            logger.info(f"Collected BTC price from Binance: ${price:,.2f} USD")
    
    def collect_24hr_stats(self):
        """Collect 24-hour trading statistics."""
        data = self.get('/api/v3/ticker/24hr', params={'symbol': 'BTCUSDT'})
        
        if data:
            ts = self.get_timestamp()
            
            # Extract statistics
            price = float(data.get('lastPrice', 0))
            volume_btc = float(data.get('volume', 0))
            volume_usd = float(data.get('quoteVolume', 0))
            high_24h = float(data.get('highPrice', 0))
            low_24h = float(data.get('lowPrice', 0))
            change_24h = float(data.get('priceChangePercent', 0))
            
            # Store metrics
            upsert_metric('price.btc_usd', price, ts, 'USD')
            upsert_metric('price.volume_24h_btc', volume_btc, ts, 'BTC')
            upsert_metric('price.volume_24h_usd', volume_usd, ts, 'USD')
            upsert_metric('price.high_24h', high_24h, ts, 'USD')
            upsert_metric('price.low_24h', low_24h, ts, 'USD')
            upsert_metric('price.change_24h', change_24h, ts, '%')
            
            # Calculate volatility
            if high_24h > 0 and low_24h > 0:
                volatility = ((high_24h - low_24h) / low_24h) * 100
                upsert_metric('price.volatility_24h', volatility, ts, '%')
            
            logger.info(f"Collected 24hr stats: Volume=${volume_usd:,.0f}, Change={change_24h:.2f}%")
    
    def collect_historical_prices(self, days=30):
        """Collect historical kline/candlestick data."""
        # Calculate time range
        end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_time = end_time - (days * 24 * 60 * 60 * 1000)
        
        # Get daily klines
        data = self.get('/api/v3/klines', params={
            'symbol': 'BTCUSDT',
            'interval': '1d',
            'startTime': start_time,
            'endTime': end_time,
            'limit': days
        })
        
        if data and isinstance(data, list):
            logger.info(f"Processing {len(data)} days of historical data from Binance")
            
            for kline in data:
                # Kline format: [openTime, open, high, low, close, volume, closeTime, ...]
                if len(kline) >= 7:
                    ts = kline[0] // 1000  # Convert ms to seconds
                    open_price = float(kline[1])
                    high_price = float(kline[2])
                    low_price = float(kline[3])
                    close_price = float(kline[4])
                    volume_btc = float(kline[5])
                    
                    # Store daily price data
                    store_json_data('raw_price', {
                        'ts': ts,
                        'price_usd': close_price,
                        'volume_24h': volume_btc * close_price,
                        'market_cap': close_price * 19500000
                    })
                    
                    # Store OHLC metrics
                    upsert_metric('price.open', open_price, ts, 'USD')
                    upsert_metric('price.high', high_price, ts, 'USD')
                    upsert_metric('price.low', low_price, ts, 'USD')
                    upsert_metric('price.close', close_price, ts, 'USD')
                    
                    # Calculate daily volatility
                    daily_volatility = ((high_price - low_price) / low_price) * 100
                    upsert_metric('price.daily_volatility', daily_volatility, ts, '%')
            
            logger.info(f"Stored {len(data)} days of historical price data")
    
    def collect_order_book_depth(self):
        """Collect order book depth for liquidity analysis."""
        data = self.get('/api/v3/depth', params={
            'symbol': 'BTCUSDT',
            'limit': 100
        })
        
        if data and 'bids' in data and 'asks' in data:
            ts = self.get_timestamp()
            
            # Calculate total liquidity in top 100 levels
            bid_liquidity = sum(float(bid[0]) * float(bid[1]) for bid in data['bids'])
            ask_liquidity = sum(float(ask[0]) * float(ask[1]) for ask in data['asks'])
            total_liquidity = bid_liquidity + ask_liquidity
            
            # Calculate spread
            if data['bids'] and data['asks']:
                best_bid = float(data['bids'][0][0])
                best_ask = float(data['asks'][0][0])
                spread = best_ask - best_bid
                spread_pct = (spread / best_bid) * 100
                
                upsert_metric('market.spread', spread, ts, 'USD')
                upsert_metric('market.spread_pct', spread_pct, ts, '%')
            
            upsert_metric('market.bid_liquidity', bid_liquidity, ts, 'USD')
            upsert_metric('market.ask_liquidity', ask_liquidity, ts, 'USD')
            upsert_metric('market.total_liquidity', total_liquidity, ts, 'USD')
            
            logger.info(f"Order book depth: ${total_liquidity:,.0f} liquidity")


def main():
    """Test the Binance collector."""
    import sys
    logging.basicConfig(level=logging.INFO)
    
    collector = BinanceCollector()
    if collector.run():
        print("Binance collection successful!")
        sys.exit(0)
    else:
        print("Binance collection failed")
        sys.exit(1)


if __name__ == '__main__':
    main()