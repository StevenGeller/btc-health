"""Unit tests for score calculation."""

import unittest
from unittest.mock import Mock, patch, MagicMock
import numpy as np

from app.compute.normalize import MetricNormalizer
from app.compute.scores import ScoreCalculator
from app.compute.formulas import MetricCalculator


class TestMetricNormalizer(unittest.TestCase):
    """Test metric normalization."""
    
    def setUp(self):
        self.normalizer = MetricNormalizer(window_days=365, fallback_days=90)
    
    @patch('app.compute.normalize.get_metric_history')
    @patch('app.compute.normalize.store_percentiles')
    def test_calculate_percentiles(self, mock_store, mock_history):
        """Test percentile calculation."""
        # Mock metric history
        mock_history.return_value = [
            {'value': i} for i in range(1, 101)  # Values 1-100
        ]
        
        self.normalizer.calculate_percentiles('test.metric')
        
        # Verify percentiles were calculated and stored
        mock_store.assert_called_once()
        percentiles = mock_store.call_args[0][2]
        
        # Check percentile values
        self.assertAlmostEqual(percentiles['p10'], 10.9, places=1)
        self.assertAlmostEqual(percentiles['p50'], 50.5, places=1)
        self.assertAlmostEqual(percentiles['p90'], 90.1, places=1)
        self.assertEqual(percentiles['min'], 1)
        self.assertEqual(percentiles['max'], 100)
    
    @patch('app.compute.normalize.get_percentiles')
    def test_get_percentile_rank(self, mock_get):
        """Test percentile rank calculation."""
        mock_get.return_value = {
            'min_val': 0,
            'p10': 10,
            'p25': 25,
            'p50': 50,
            'p75': 75,
            'p90': 90,
            'max_val': 100
        }
        
        # Test various values
        self.assertEqual(self.normalizer.get_percentile_rank('test.metric', 0), 0.0)
        self.assertEqual(self.normalizer.get_percentile_rank('test.metric', 100), 1.0)
        self.assertAlmostEqual(self.normalizer.get_percentile_rank('test.metric', 50), 0.5, places=1)
        
        # Test interpolation
        rank = self.normalizer.get_percentile_rank('test.metric', 30)
        self.assertTrue(0.25 < rank < 0.5)


class TestScoreCalculator(unittest.TestCase):
    """Test score calculation."""
    
    def setUp(self):
        self.calculator = ScoreCalculator()
        
        # Mock metric definitions
        self.calculator.metrics = {
            'security.hashprice': {
                'metric_id': 'security.hashprice',
                'pillar_id': 'security',
                'direction': 'higher_better',
                'weight': 0.25,
                'target_min': None,
                'target_max': None
            },
            'adoption.rbf_activity': {
                'metric_id': 'adoption.rbf_activity',
                'pillar_id': 'adoption',
                'direction': 'target_band',
                'weight': 0.35,
                'target_min': 2,
                'target_max': 15
            }
        }
        
        # Mock pillar definitions
        self.calculator.pillars = {
            'security': {
                'pillar_id': 'security',
                'name': 'Security',
                'weight': 0.30
            },
            'adoption': {
                'pillar_id': 'adoption',
                'name': 'Adoption',
                'weight': 0.15
            }
        }
    
    @patch('app.compute.scores.get_latest_metric')
    @patch('app.compute.scores.MetricNormalizer.get_percentile_rank')
    def test_calculate_metric_score_higher_better(self, mock_rank, mock_metric):
        """Test metric score calculation for higher_better direction."""
        mock_metric.return_value = {'value': 0.1}
        mock_rank.return_value = 0.75
        
        score = self.calculator.calculate_metric_score(
            'security.hashprice',
            self.calculator.metrics['security.hashprice']
        )
        
        self.assertEqual(score, 75.0)
    
    @patch('app.compute.scores.get_latest_metric')
    def test_calculate_metric_score_target_band(self, mock_metric):
        """Test metric score calculation for target band."""
        definition = self.calculator.metrics['adoption.rbf_activity']
        
        # Test value in band
        mock_metric.return_value = {'value': 8.5}  # Center of band
        score = self.calculator.calculate_metric_score('adoption.rbf_activity', definition)
        self.assertEqual(score, 100.0)
        
        # Test value below band
        mock_metric.return_value = {'value': 1}
        score = self.calculator.calculate_metric_score('adoption.rbf_activity', definition)
        self.assertTrue(0 <= score < 50)
        
        # Test value above band
        mock_metric.return_value = {'value': 20}
        score = self.calculator.calculate_metric_score('adoption.rbf_activity', definition)
        self.assertTrue(0 <= score < 50)
    
    def test_calculate_pillar_score(self):
        """Test pillar score calculation."""
        metric_scores = {
            'security.hashprice': 80.0,
            'security.fee_share': 60.0,
            'security.difficulty_momentum': 90.0
        }
        
        # Add more metrics to calculator
        self.calculator.metrics.update({
            'security.fee_share': {
                'pillar_id': 'security',
                'weight': 0.25
            },
            'security.difficulty_momentum': {
                'pillar_id': 'security',
                'weight': 0.25
            }
        })
        
        score = self.calculator.calculate_pillar_score('security', metric_scores)
        
        # Weighted average: (80*0.25 + 60*0.25 + 90*0.25) / 0.75
        expected = (20 + 15 + 22.5) / 0.75
        self.assertAlmostEqual(score, expected, places=1)
    
    def test_calculate_overall_score(self):
        """Test overall score calculation."""
        pillar_scores = {
            'security': 75.0,
            'adoption': 85.0
        }
        
        score = self.calculator.calculate_overall_score(pillar_scores)
        
        # Weighted average: (75*0.30 + 85*0.15) / 0.45
        expected = (22.5 + 12.75) / 0.45
        self.assertAlmostEqual(score, expected, places=1)


class TestMetricCalculator(unittest.TestCase):
    """Test metric formula calculations."""
    
    def setUp(self):
        self.calculator = MetricCalculator()
    
    @patch('app.compute.formulas.get_latest_metric')
    @patch('app.compute.formulas.execute_query')
    @patch('app.compute.formulas.upsert_metric')
    def test_calculate_hashprice(self, mock_upsert, mock_query, mock_metric):
        """Test hashprice calculation."""
        # Mock difficulty
        mock_metric.return_value = {'value': 50_000_000_000_000}
        
        # Mock block rewards
        mock_query.return_value = [{
            'avg_fee_per_block': 0.1,
            'subsidy_btc': 6.25
        }]
        
        # Mock price (need to patch multiple calls)
        mock_metric.side_effect = [
            {'value': 50_000_000_000_000},  # difficulty
            {'value': 45000}  # price
        ]
        
        self.calculator.calculate_hashprice()
        
        # Verify metric was stored
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args[0]
        self.assertEqual(call_args[0], 'security.hashprice')
        
        # Check hashprice is reasonable (should be positive)
        hashprice = call_args[1]
        self.assertGreater(hashprice, 0)
    
    @patch('app.compute.formulas.execute_query')
    @patch('app.compute.formulas.upsert_metric')
    def test_calculate_pool_hhi(self, mock_upsert, mock_query):
        """Test mining pool HHI calculation."""
        mock_query.return_value = [
            {'ts': 1234567890, 'pool': 'Pool1', 'share': 30},
            {'ts': 1234567890, 'pool': 'Pool2', 'share': 25},
            {'ts': 1234567890, 'pool': 'Pool3', 'share': 20},
            {'ts': 1234567890, 'pool': 'Pool4', 'share': 15},
            {'ts': 1234567890, 'pool': 'Pool5', 'share': 10}
        ]
        
        self.calculator.calculate_pool_hhi()
        
        # Verify HHI was calculated and stored
        mock_upsert.assert_any_call('decent.pool_hhi', unittest.mock.ANY, unittest.mock.ANY)
        
        # Get HHI value
        hhi_call = [call for call in mock_upsert.call_args_list 
                   if call[0][0] == 'decent.pool_hhi'][0]
        hhi = hhi_call[0][1]
        
        # Expected HHI = 0.3^2 + 0.25^2 + 0.2^2 + 0.15^2 + 0.1^2
        expected_hhi = 0.09 + 0.0625 + 0.04 + 0.0225 + 0.01
        self.assertAlmostEqual(hhi, expected_hhi, places=4)


if __name__ == '__main__':
    unittest.main()
