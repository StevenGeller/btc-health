"""Normalize metrics using rolling percentiles."""

import logging
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta

from app.storage.db import (
    execute_query, get_metric_history, store_percentiles,
    get_percentiles, update_meta_config
)

logger = logging.getLogger(__name__)


class MetricNormalizer:
    """Normalize metrics using rolling window percentiles."""
    
    def __init__(self, window_days: int = 365, fallback_days: int = 90):
        """
        Initialize normalizer.
        
        Args:
            window_days: Primary window for percentile calculation
            fallback_days: Fallback window if insufficient data
        """
        self.window_days = window_days
        self.fallback_days = fallback_days
    
    def normalize_all(self):
        """Calculate percentiles for all metrics."""
        # Get list of all metrics
        metrics = execute_query(
            """
            SELECT DISTINCT metric_id FROM metrics
            ORDER BY metric_id
            """
        )
        
        if not metrics:
            logger.warning("No metrics found to normalize")
            return
        
        ts = int(datetime.now(timezone.utc).timestamp())
        
        for metric_row in metrics:
            metric_id = metric_row['metric_id']
            self.calculate_percentiles(metric_id, ts)
        
        # Update metadata
        update_meta_config('last_normalization', datetime.now(timezone.utc).isoformat())
        logger.info(f"Completed normalization for {len(metrics)} metrics")
    
    def calculate_percentiles(self, metric_id: str, ts: Optional[int] = None):
        """
        Calculate and store percentiles for a metric.
        
        Args:
            metric_id: Metric identifier
            ts: Timestamp for the percentile calculation
        """
        if ts is None:
            ts = int(datetime.now(timezone.utc).timestamp())
        
        # Try primary window first
        history = get_metric_history(metric_id, self.window_days)
        window_used = self.window_days
        
        # Fall back to shorter window if insufficient data
        if len(history) < 30:  # Need at least 30 data points
            history = get_metric_history(metric_id, self.fallback_days)
            window_used = self.fallback_days
            
            if len(history) < 10:  # Absolute minimum
                logger.warning(f"Insufficient data for {metric_id}: only {len(history)} points")
                return
        
        # Extract values
        values = [h['value'] for h in history]
        
        # Calculate percentiles
        percentiles = {
            'p10': np.percentile(values, 10),
            'p25': np.percentile(values, 25),
            'p50': np.percentile(values, 50),
            'p75': np.percentile(values, 75),
            'p90': np.percentile(values, 90),
            'min': np.min(values),
            'max': np.max(values)
        }
        
        # Store percentiles
        store_percentiles(metric_id, window_used, percentiles, ts)
        
        logger.debug(f"Calculated percentiles for {metric_id} using {window_used}d window: "
                    f"p50={percentiles['p50']:.4f}, range=[{percentiles['min']:.4f}, {percentiles['max']:.4f}]")
    
    def get_percentile_rank(self, metric_id: str, value: float, 
                           window_days: Optional[int] = None) -> Optional[float]:
        """
        Get percentile rank of a value within historical distribution.
        
        Args:
            metric_id: Metric identifier
            value: Value to rank
            window_days: Window to use (defaults to primary window)
            
        Returns:
            Percentile rank (0-1) or None if no data
        """
        if window_days is None:
            window_days = self.window_days
        
        # Get stored percentiles
        pctl_data = get_percentiles(metric_id, window_days)
        
        if not pctl_data:
            # Try fallback window
            pctl_data = get_percentiles(metric_id, self.fallback_days)
            if not pctl_data:
                return None
        
        # Interpolate rank based on percentiles
        if value <= pctl_data['min_val']:
            return 0.0
        elif value >= pctl_data['max_val']:
            return 1.0
        elif value <= pctl_data['p10']:
            # Linear interpolation between min and p10
            return 0.1 * (value - pctl_data['min_val']) / (pctl_data['p10'] - pctl_data['min_val'])
        elif value <= pctl_data['p25']:
            return 0.1 + 0.15 * (value - pctl_data['p10']) / (pctl_data['p25'] - pctl_data['p10'])
        elif value <= pctl_data['p50']:
            return 0.25 + 0.25 * (value - pctl_data['p25']) / (pctl_data['p50'] - pctl_data['p25'])
        elif value <= pctl_data['p75']:
            return 0.5 + 0.25 * (value - pctl_data['p50']) / (pctl_data['p75'] - pctl_data['p50'])
        elif value <= pctl_data['p90']:
            return 0.75 + 0.15 * (value - pctl_data['p75']) / (pctl_data['p90'] - pctl_data['p75'])
        else:
            # Linear interpolation between p90 and max
            return 0.9 + 0.1 * (value - pctl_data['p90']) / (pctl_data['max_val'] - pctl_data['p90'])


def main():
    """Run normalization."""
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    normalizer = MetricNormalizer()
    try:
        normalizer.normalize_all()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Normalization failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
