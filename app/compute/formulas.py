"""Formula implementations for Bitcoin health metrics."""

import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone
import numpy as np

from app.storage.db import execute_query, upsert_metric, get_latest_metric

logger = logging.getLogger(__name__)


class MetricCalculator:
    """Calculate derived metrics from raw data."""
    
    def calculate_all(self):
        """Calculate all derived metrics."""
        ts = int(datetime.now(timezone.utc).timestamp())
        
        self.calculate_hashprice()
        self.calculate_fee_share()
        self.calculate_pool_hhi()
        self.calculate_fee_elasticity()
        self.calculate_segwit_adoption()
        self.calculate_lightning_growth()
        self.calculate_difficulty_momentum()
        
        logger.info("Completed all metric calculations")
    
    def calculate_hashprice(self):
        """Calculate hashprice in USD/TH/day."""
        # Get current difficulty
        difficulty_data = get_latest_metric('security.difficulty')
        if not difficulty_data:
            # Try to get from raw data
            diff_raw = execute_query(
                "SELECT * FROM raw_difficulty_estimate ORDER BY ts DESC LIMIT 1"
            )
            if not diff_raw:
                logger.warning("No difficulty data available for hashprice calculation")
                return
            # Use a default difficulty if not available
            difficulty = 50_000_000_000_000  # Approximate current difficulty
        else:
            difficulty = difficulty_data['value']
        
        # Get average block reward (fees + subsidy)
        rewards = execute_query(
            "SELECT * FROM raw_block_rewards ORDER BY day DESC LIMIT 1"
        )
        if not rewards:
            logger.warning("No block reward data available")
            return
        
        reward_data = rewards[0]
        avg_fees_btc = reward_data.get('avg_fee_per_block', 0) or 0
        subsidy_btc = 6.25  # Current subsidy (update after halving)
        total_reward_btc = avg_fees_btc + subsidy_btc
        
        # Get BTC price
        price_data = get_latest_metric('price.btc_usd')
        if not price_data:
            logger.warning("No price data available")
            return
        
        price_usd = price_data['value']
        
        # Calculate hashprice
        # Network hashrate in hashes/second = difficulty * 2^32 / 600
        # Daily hashes = hashrate * 86400
        # Daily revenue = blocks_per_day * reward * price = 144 * total_reward_btc * price_usd
        # Hashprice = daily_revenue / daily_hashes
        
        hashrate_per_sec = difficulty * (2**32) / 600  # hashes per second
        daily_hashes = hashrate_per_sec * 86400
        daily_revenue_usd = 144 * total_reward_btc * price_usd
        
        # Convert to USD per TH per day (1 TH = 10^12 hashes)
        hashprice_usd_per_th_day = (daily_revenue_usd / daily_hashes) * 1e12
        
        ts = int(datetime.now(timezone.utc).timestamp())
        upsert_metric('security.hashprice', hashprice_usd_per_th_day, ts, 'USD/TH/day')
        
        logger.info(f"Calculated hashprice: ${hashprice_usd_per_th_day:.4f} USD/TH/day")
    
    def calculate_fee_share(self):
        """Calculate 30-day average fee share of miner revenue."""
        # Get last 30 days of block rewards
        cutoff = int(datetime.now(timezone.utc).timestamp()) - (30 * 86400)
        
        rewards = execute_query(
            """
            SELECT SUM(fees_btc) as total_fees, SUM(subsidy_btc) as total_subsidy
            FROM raw_block_rewards
            WHERE day >= date('now', '-30 days')
            """
        )
        
        if rewards and rewards[0]['total_fees']:
            total_fees = rewards[0]['total_fees']
            total_subsidy = rewards[0]['total_subsidy']
            total_revenue = total_fees + total_subsidy
            
            if total_revenue > 0:
                fee_share = total_fees / total_revenue
                
                ts = int(datetime.now(timezone.utc).timestamp())
                upsert_metric('security.fee_share', fee_share, ts)
                
                logger.info(f"Calculated 30d fee share: {fee_share:.2%}")
    
    def calculate_pool_hhi(self):
        """Calculate mining pool Herfindahl-Hirschman Index."""
        # Get pool shares from last 24 hours
        cutoff = int(datetime.now(timezone.utc).timestamp()) - 86400
        
        pools = execute_query(
            """
            SELECT pool, share FROM raw_pool_shares
            WHERE ts >= ?
            ORDER BY ts DESC, share DESC
            """,
            (cutoff,)
        )
        
        if pools:
            # Get most recent snapshot
            latest_ts = pools[0]['ts'] if pools else 0
            current_pools = [p for p in pools if p['ts'] == latest_ts]
            
            # Calculate HHI
            total_share = sum(p['share'] for p in current_pools)
            if total_share > 0:
                # Normalize shares to sum to 1
                shares = [p['share'] / total_share for p in current_pools]
                hhi = sum(s ** 2 for s in shares)
                
                ts = int(datetime.now(timezone.utc).timestamp())
                upsert_metric('decent.pool_hhi', hhi, ts)
                
                # Also calculate top-3 concentration
                sorted_shares = sorted(shares, reverse=True)
                top3_share = sum(sorted_shares[:3])
                upsert_metric('decent.pool_top3', top3_share, ts)
                
                logger.info(f"Calculated pool HHI: {hhi:.4f}, Top-3: {top3_share:.2%}")
    
    def calculate_fee_elasticity(self):
        """Calculate correlation between mempool size and fee rates."""
        # Get last 30 days of mempool and fee data
        cutoff = int(datetime.now(timezone.utc).timestamp()) - (30 * 86400)
        
        mempool_data = execute_query(
            """
            SELECT ts, vsize FROM raw_mempool_snapshot
            WHERE ts >= ?
            ORDER BY ts
            """,
            (cutoff,)
        )
        
        fee_data = execute_query(
            """
            SELECT ts, value FROM metrics
            WHERE metric_id = 'fees.halfhour' AND ts >= ?
            ORDER BY ts
            """,
            (cutoff,)
        )
        
        if len(mempool_data) > 10 and len(fee_data) > 10:
            # Align timestamps and interpolate
            mempool_sizes = []
            fee_rates = []
            
            for m in mempool_data:
                # Find closest fee data point
                closest_fee = min(fee_data, key=lambda f: abs(f['ts'] - m['ts']))
                if abs(closest_fee['ts'] - m['ts']) < 3600:  # Within 1 hour
                    mempool_sizes.append(m['vsize'])
                    fee_rates.append(closest_fee['value'])
            
            if len(mempool_sizes) > 10:
                # Calculate Pearson correlation
                correlation = np.corrcoef(mempool_sizes, fee_rates)[0, 1]
                
                ts = int(datetime.now(timezone.utc).timestamp())
                upsert_metric('throughput.fee_elasticity', correlation, ts)
                
                logger.info(f"Calculated fee elasticity: {correlation:.4f}")
    
    def calculate_segwit_adoption(self):
        """Calculate SegWit adoption percentage."""
        # Get latest SegWit stats
        stats = execute_query(
            """
            SELECT * FROM raw_segwit_stats
            ORDER BY day DESC
            LIMIT 1
            """
        )
        
        if stats:
            stat = stats[0]
            if stat['total_tx_count'] > 0:
                segwit_pct = stat['segwit_tx_count'] / stat['total_tx_count']
                
                ts = int(datetime.now(timezone.utc).timestamp())
                upsert_metric('adoption.segwit_usage', segwit_pct, ts)
                
                logger.info(f"Calculated SegWit adoption: {segwit_pct:.2%}")
            
            if stat['total_weight'] > 0:
                segwit_weight_pct = stat['segwit_weight'] / stat['total_weight']
                upsert_metric('adoption.segwit_weight', segwit_weight_pct, ts)
    
    def calculate_lightning_growth(self):
        """Calculate Lightning Network growth rates."""
        # Get Lightning stats for different periods
        current = execute_query(
            """
            SELECT * FROM raw_ln_stats
            ORDER BY day DESC
            LIMIT 1
            """
        )
        
        month_ago = execute_query(
            """
            SELECT * FROM raw_ln_stats
            WHERE day <= date('now', '-30 days')
            ORDER BY day DESC
            LIMIT 1
            """
        )
        
        if current and month_ago:
            curr = current[0]
            prev = month_ago[0]
            
            # Calculate 30-day growth rates
            if prev['capacity_btc'] > 0:
                capacity_growth = ((curr['capacity_btc'] - prev['capacity_btc']) / prev['capacity_btc'])
                
                ts = int(datetime.now(timezone.utc).timestamp())
                upsert_metric('lightning.capacity_growth', capacity_growth, ts)
                
                logger.info(f"Lightning capacity 30d growth: {capacity_growth:.2%}")
            
            if prev['channels'] > 0:
                channel_growth = ((curr['channels'] - prev['channels']) / prev['channels'])
                upsert_metric('lightning.channel_growth', channel_growth, ts)
    
    def calculate_difficulty_momentum(self):
        """Calculate difficulty adjustment momentum."""
        # Get latest difficulty estimate
        diff_est = execute_query(
            """
            SELECT * FROM raw_difficulty_estimate
            ORDER BY ts DESC
            LIMIT 1
            """
        )
        
        if diff_est:
            est = diff_est[0]
            est_change = abs(est['est_change'])
            
            # Score is inverse of change magnitude
            # Small changes (< 5%) are healthy, large changes indicate instability
            if est_change < 5:
                momentum_score = 1.0
            elif est_change < 10:
                momentum_score = 0.75
            elif est_change < 20:
                momentum_score = 0.5
            elif est_change < 40:
                momentum_score = 0.25
            else:
                momentum_score = 0.0
            
            ts = int(datetime.now(timezone.utc).timestamp())
            upsert_metric('security.difficulty_momentum', momentum_score, ts)
            
            logger.info(f"Difficulty momentum score: {momentum_score:.2f} (est change: {est['est_change']:.1f}%)")


def main():
    """Run metric calculations."""
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    calculator = MetricCalculator()
    try:
        calculator.calculate_all()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Metric calculation failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
