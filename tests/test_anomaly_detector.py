"""
Unit tests for anomaly detection module.
"""

import pytest
import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from detection.anomaly_detector import calculate_zscore, detect_anomalies


class TestCalculateZscore:
    """Tests for z-score calculation."""

    def test_zscore_mean_is_zero(self):
        """Test that z-score of mean value is 0."""
        series = pd.Series([10, 20, 30, 40, 50])
        zscores = calculate_zscore(series)
        
        # Middle value should have z-score close to 0
        assert abs(zscores.iloc[2]) < 0.1

    def test_zscore_standard_deviation(self):
        """Test z-score scaling."""
        series = pd.Series([0, 0, 0, 0, 10])
        zscores = calculate_zscore(series)
        
        # Last value should have high z-score
        assert zscores.iloc[-1] > 1


class TestDetectAnomalies:
    """Tests for anomaly detection."""

    def test_no_anomalies_in_stable_data(self):
        """Test that stable data has no anomalies."""
        df = pd.DataFrame({
            'metric_date': pd.date_range('2024-01-01', periods=10),
            'total_revenue': [100, 102, 98, 101, 99, 100, 103, 97, 101, 100]
        })
        
        result = detect_anomalies(df, 'total_revenue', threshold=2.0)
        
        assert result['is_anomaly'].sum() == 0

    def test_detects_obvious_anomaly(self):
        """Test that obvious outlier is detected."""
        df = pd.DataFrame({
            'metric_date': pd.date_range('2024-01-01', periods=10),
            'total_revenue': [100, 100, 100, 100, 100, 100, 100, 100, 100, 500]
        })
        
        result = detect_anomalies(df, 'total_revenue', threshold=2.0)
        
        assert result['is_anomaly'].sum() >= 1

    def test_anomaly_direction(self):
        """Test anomaly direction labeling."""
        df = pd.DataFrame({
            'metric_date': pd.date_range('2024-01-01', periods=5),
            'total_revenue': [100, 100, 100, 100, 10]
        })
        
        result = detect_anomalies(df, 'total_revenue', threshold=1.5)
        
        low_anomalies = result[result['anomaly_direction'] == 'low']
        assert len(low_anomalies) >= 1
