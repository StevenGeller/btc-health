"""Calculate health scores from normalized metrics."""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone

from app.storage.db import (
    execute_query, upsert_score, get_latest_metric,
    update_meta_config
)
from app.compute.normalize import MetricNormalizer

logger = logging.getLogger(__name__)


class ScoreCalculator:
    """Calculate health scores from metrics."""
    
    def __init__(self):
        self.normalizer = MetricNormalizer()
        self.load_definitions()
    
    def load_definitions(self):
        """Load metric and pillar definitions from database."""
        self.pillars = {}
        pillar_rows = execute_query("SELECT * FROM pillar_definitions")
        for row in pillar_rows:
            self.pillars[row['pillar_id']] = row
        
        self.metrics = {}
        metric_rows = execute_query("SELECT * FROM metric_definitions")
        for row in metric_rows:
            self.metrics[row['metric_id']] = row
    
    def calculate_all(self):
        """Calculate all scores."""
        ts = int(datetime.now(timezone.utc).timestamp())
        
        # Calculate metric scores
        metric_scores = {}
        for metric_id, definition in self.metrics.items():
            score = self.calculate_metric_score(metric_id, definition)
            if score is not None:
                metric_scores[metric_id] = score
                
                # Calculate trend
                trend_7d = self.calculate_trend(metric_id, 7)
                trend_30d = self.calculate_trend(metric_id, 30)
                
                upsert_score('metric', metric_id, score, ts, trend_7d, trend_30d)
                logger.debug(f"Metric {metric_id}: {score:.1f}/100")
        
        # Calculate pillar scores
        pillar_scores = {}
        for pillar_id, pillar_def in self.pillars.items():
            score = self.calculate_pillar_score(pillar_id, metric_scores)
            if score is not None:
                pillar_scores[pillar_id] = score
                
                # Calculate trend
                trend_7d = self.calculate_pillar_trend(pillar_id, 7)
                trend_30d = self.calculate_pillar_trend(pillar_id, 30)
                
                upsert_score('pillar', pillar_id, score, ts, trend_7d, trend_30d)
                logger.info(f"Pillar {pillar_id}: {score:.1f}/100")
        
        # Calculate overall score
        overall_score = self.calculate_overall_score(pillar_scores)
        if overall_score is not None:
            # Calculate trend
            trend_7d = self.calculate_overall_trend(7)
            trend_30d = self.calculate_overall_trend(30)
            
            upsert_score('overall', 'overall', overall_score, ts, trend_7d, trend_30d)
            logger.info(f"Overall score: {overall_score:.1f}/100")
        
        # Update metadata
        update_meta_config('last_computation', datetime.now(timezone.utc).isoformat())
        logger.info("Completed score calculations")
    
    def calculate_metric_score(self, metric_id: str, definition: Dict) -> Optional[float]:
        """
        Calculate score for a single metric.
        
        Args:
            metric_id: Metric identifier
            definition: Metric definition with direction and targets
            
        Returns:
            Score (0-100) or None if no data
        """
        # Get latest metric value
        metric_data = get_latest_metric(metric_id)
        if not metric_data:
            logger.warning(f"No data for metric {metric_id}")
            return None
        
        value = metric_data['value']
        direction = definition['direction']
        
        if direction == 'target_band':
            # Score based on distance from target band
            target_min = definition['target_min']
            target_max = definition['target_max']
            
            if target_min is None or target_max is None:
                logger.warning(f"No target band defined for {metric_id}")
                return 50.0  # Default to middle score
            
            target_center = (target_min + target_max) / 2
            target_range = target_max - target_min
            
            if target_min <= value <= target_max:
                # Within band - score based on distance from center
                distance_from_center = abs(value - target_center)
                score = 100 * (1 - distance_from_center / (target_range / 2))
            elif value < target_min:
                # Below band
                distance = target_min - value
                score = max(0, 50 * (1 - distance / target_min))
            else:
                # Above band
                distance = value - target_max
                score = max(0, 50 * (1 - distance / target_max))
            
            return score
        
        else:
            # Score based on percentile rank
            rank = self.normalizer.get_percentile_rank(metric_id, value)
            
            if rank is None:
                logger.warning(f"No percentile data for {metric_id}")
                return None
            
            if direction == 'higher_better':
                score = rank * 100
            elif direction == 'lower_better':
                score = (1 - rank) * 100
            else:
                logger.warning(f"Unknown direction {direction} for {metric_id}")
                return None
            
            return score
    
    def calculate_pillar_score(self, pillar_id: str, metric_scores: Dict[str, float]) -> Optional[float]:
        """
        Calculate score for a pillar.
        
        Args:
            pillar_id: Pillar identifier
            metric_scores: Dictionary of metric scores
            
        Returns:
            Weighted average score (0-100) or None if no metrics
        """
        # Get metrics for this pillar
        pillar_metrics = [m for m_id, m in self.metrics.items() 
                         if m['pillar_id'] == pillar_id]
        
        if not pillar_metrics:
            logger.warning(f"No metrics defined for pillar {pillar_id}")
            return None
        
        total_weight = 0
        weighted_sum = 0
        
        for metric in pillar_metrics:
            metric_id = metric['metric_id']
            weight = metric['weight'] or 1.0
            
            if metric_id in metric_scores:
                score = metric_scores[metric_id]
                weighted_sum += score * weight
                total_weight += weight
            else:
                logger.debug(f"No score for metric {metric_id} in pillar {pillar_id}")
        
        if total_weight == 0:
            return None
        
        return weighted_sum / total_weight
    
    def calculate_overall_score(self, pillar_scores: Dict[str, float]) -> Optional[float]:
        """
        Calculate overall health score.
        
        Args:
            pillar_scores: Dictionary of pillar scores
            
        Returns:
            Weighted average score (0-100) or None if no pillars
        """
        total_weight = 0
        weighted_sum = 0
        
        for pillar_id, pillar_def in self.pillars.items():
            weight = pillar_def['weight'] or 0
            
            if pillar_id in pillar_scores:
                score = pillar_scores[pillar_id]
                weighted_sum += score * weight
                total_weight += weight
            else:
                logger.warning(f"No score for pillar {pillar_id}")
        
        if total_weight == 0:
            return None
        
        return weighted_sum / total_weight
    
    def calculate_trend(self, metric_id: str, days: int) -> Optional[float]:
        """Calculate percentage change in metric score over time."""
        current = execute_query(
            """
            SELECT score FROM scores
            WHERE kind = 'metric' AND id = ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (metric_id,)
        )
        
        if not current:
            return None
        
        cutoff = int(datetime.now(timezone.utc).timestamp()) - (days * 86400)
        historical = execute_query(
            """
            SELECT score FROM scores
            WHERE kind = 'metric' AND id = ? AND ts <= ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (metric_id, cutoff)
        )
        
        if not historical:
            return None
        
        current_score = current[0]['score']
        historical_score = historical[0]['score']
        
        if historical_score == 0:
            return None
        
        return ((current_score - historical_score) / historical_score) * 100
    
    def calculate_pillar_trend(self, pillar_id: str, days: int) -> Optional[float]:
        """Calculate percentage change in pillar score over time."""
        current = execute_query(
            """
            SELECT score FROM scores
            WHERE kind = 'pillar' AND id = ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (pillar_id,)
        )
        
        if not current:
            return None
        
        cutoff = int(datetime.now(timezone.utc).timestamp()) - (days * 86400)
        historical = execute_query(
            """
            SELECT score FROM scores
            WHERE kind = 'pillar' AND id = ? AND ts <= ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (pillar_id, cutoff)
        )
        
        if not historical:
            return None
        
        current_score = current[0]['score']
        historical_score = historical[0]['score']
        
        if historical_score == 0:
            return None
        
        return ((current_score - historical_score) / historical_score) * 100
    
    def calculate_overall_trend(self, days: int) -> Optional[float]:
        """Calculate percentage change in overall score over time."""
        current = execute_query(
            """
            SELECT score FROM scores
            WHERE kind = 'overall' AND id = 'overall'
            ORDER BY ts DESC
            LIMIT 1
            """
        )
        
        if not current:
            return None
        
        cutoff = int(datetime.now(timezone.utc).timestamp()) - (days * 86400)
        historical = execute_query(
            """
            SELECT score FROM scores
            WHERE kind = 'overall' AND id = 'overall' AND ts <= ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (cutoff,)
        )
        
        if not historical:
            return None
        
        current_score = current[0]['score']
        historical_score = historical[0]['score']
        
        if historical_score == 0:
            return None
        
        return ((current_score - historical_score) / historical_score) * 100


def main():
    """Run score calculations."""
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    calculator = ScoreCalculator()
    try:
        calculator.calculate_all()
        sys.exit(0)
    except Exception as e:
        logger.error(f"Score calculation failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
