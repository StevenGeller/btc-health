#!/usr/bin/env python3
"""Generate synthetic historical data for demonstration purposes."""

import sys
import os
import random
from pathlib import Path
from datetime import datetime, timedelta, timezone
import numpy as np

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.storage.db import execute_insert, upsert_metric, upsert_score
from app.compute.scores import ScoreCalculator

def generate_demo_data(days=30):
    """Generate synthetic historical data for demo purposes."""
    print(f"Generating {days} days of synthetic historical data...")
    
    now = datetime.now(timezone.utc)
    base_price = 110000
    base_hashrate = 750000000  # 750 EH/s
    base_difficulty = 95670000000000
    
    for day_offset in range(days, 0, -1):
        # Generate data points every 4 hours
        for hour in [0, 4, 8, 12, 16, 20]:
            current_time = now - timedelta(days=day_offset, hours=-hour)
            ts = int(current_time.timestamp())
            
            # Add some realistic variation
            daily_variation = np.sin(day_offset * 0.2) * 0.1
            hourly_variation = np.sin(hour * 0.5) * 0.05
            
            # Generate price data with realistic volatility
            price_variation = (1 + daily_variation + hourly_variation + random.gauss(0, 0.02))
            price = base_price * price_variation
            
            # Generate hashrate with growth trend
            hashrate_growth = 1 + (30 - day_offset) * 0.001  # 0.1% daily growth
            hashrate = base_hashrate * hashrate_growth * (1 + random.gauss(0, 0.01))
            
            # Calculate hashprice
            blocks_per_day = 144
            block_reward = 3.125
            daily_revenue = blocks_per_day * block_reward * price
            hashprice = daily_revenue / (hashrate / 1000000)  # USD per TH/day
            
            # Store metrics
            upsert_metric('security.hashrate', hashrate, ts, 'TH/s')
            upsert_metric('security.difficulty', base_difficulty * hashrate_growth, ts)
            upsert_metric('security.hashprice', hashprice, ts, 'USD/TH/day')
            upsert_metric('security.difficulty_momentum', 
                         1 + random.gauss(0, 0.05), ts)  # Score around 1.0
            
            # Mempool metrics
            mempool_size = 300000 + random.randint(-100000, 200000)
            upsert_metric('throughput.mempool_bytes', mempool_size, ts, 'bytes')
            upsert_metric('throughput.tx_per_block', 
                         3000 + random.randint(-500, 500), ts)
            
            # Fee metrics
            fee_rate = 1 + abs(random.gauss(0, 10))
            upsert_metric('fees.fast', fee_rate, ts, 'sat/vB')
            upsert_metric('fees.medium', fee_rate * 0.7, ts, 'sat/vB')
            upsert_metric('fees.slow', fee_rate * 0.4, ts, 'sat/vB')
            
            # Adoption metrics
            segwit_adoption = 85 + (30 - day_offset) * 0.1 + random.gauss(0, 2)
            upsert_metric('adoption.segwit_usage', min(100, max(0, segwit_adoption)), ts, '%')
            
            # UTXO growth
            utxo_count = 169000000 + (30 - day_offset) * 10000 + random.randint(-5000, 5000)
            upsert_metric('adoption.utxo_count', utxo_count, ts)
            
            # Lightning metrics
            ln_capacity = 5000 + (30 - day_offset) * 10 + random.gauss(0, 50)
            upsert_metric('lightning.capacity', ln_capacity, ts, 'BTC')
            upsert_metric('lightning.nodes', 15000 + (30 - day_offset) * 50, ts)
            
            # Decentralization metrics (pool HHI)
            pool_hhi = 0.08 + random.gauss(0, 0.01)  # Around 0.08 (moderate concentration)
            upsert_metric('decent.pool_hhi', max(0, min(1, pool_hhi)), ts)
            
    # Store raw price data for the API
    for day_offset in range(days, 0, -1):
        current_time = now - timedelta(days=day_offset)
        ts = int(current_time.timestamp())
        price_variation = (1 + np.sin(day_offset * 0.2) * 0.1 + random.gauss(0, 0.02))
        price = base_price * price_variation
        
        execute_insert("""
            INSERT OR REPLACE INTO raw_price (ts, price_usd, volume_24h, market_cap)
            VALUES (?, ?, ?, ?)
        """, (ts, price, random.uniform(20e9, 40e9), price * 19.5e6))
    
    # Calculate percentiles for normalization
    print("Calculating percentiles...")
    metrics_to_percentile = [
        'security.hashprice', 'security.difficulty_momentum',
        'throughput.mempool_bytes', 'adoption.segwit_usage',
        'decent.pool_hhi'
    ]
    
    for metric_id in metrics_to_percentile:
        # Get all values for this metric
        values = execute_insert("""
            SELECT value FROM metrics 
            WHERE metric_id = ? 
            ORDER BY value
        """, (metric_id,))
        
        if values and len(values) > 10:
            values_list = [v[0] for v in values]
            percentiles = {
                'p10': np.percentile(values_list, 10),
                'p25': np.percentile(values_list, 25),
                'p50': np.percentile(values_list, 50),
                'p75': np.percentile(values_list, 75),
                'p90': np.percentile(values_list, 90)
            }
            
            execute_insert("""
                INSERT OR REPLACE INTO percentiles 
                (metric_id, p10, p25, p50, p75, p90, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (metric_id, percentiles['p10'], percentiles['p25'], 
                 percentiles['p50'], percentiles['p75'], percentiles['p90'],
                 int(now.timestamp())))
    
    # Generate some scores
    print("Calculating scores...")
    for day_offset in range(min(7, days), 0, -1):
        current_time = now - timedelta(days=day_offset)
        ts = int(current_time.timestamp())
        
        # Generate pillar scores (0-100 scale)
        security_score = 75 + random.gauss(0, 5)
        decent_score = 65 + random.gauss(0, 5)
        throughput_score = 80 + random.gauss(0, 5)
        adoption_score = 70 + random.gauss(0, 5)
        lightning_score = 60 + random.gauss(0, 5)
        
        # Store pillar scores
        upsert_score('pillar', 'security', security_score, ts)
        upsert_score('pillar', 'decent', decent_score, ts)
        upsert_score('pillar', 'throughput', throughput_score, ts)
        upsert_score('pillar', 'adoption', adoption_score, ts)
        upsert_score('pillar', 'lightning', lightning_score, ts)
        
        # Calculate overall score
        overall = np.mean([security_score, decent_score, throughput_score, 
                          adoption_score, lightning_score])
        upsert_score('overall', 'bitcoin', overall, ts)
    
    # Check what we generated
    metrics_count = execute_insert("SELECT COUNT(*) FROM metrics")[0][0]
    scores_count = execute_insert("SELECT COUNT(*) FROM scores")[0][0]
    percentiles_count = execute_insert("SELECT COUNT(*) FROM percentiles")[0][0]
    
    print(f"\n✓ Generated demo data successfully!")
    print(f"  - {metrics_count} metric data points")
    print(f"  - {scores_count} score records")
    print(f"  - {percentiles_count} percentile records")
    print(f"\nThe dashboard should now display data!")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Generate demo data')
    parser.add_argument('--days', type=int, default=30,
                       help='Number of days of data to generate (default: 30)')
    args = parser.parse_args()
    
    generate_demo_data(args.days)