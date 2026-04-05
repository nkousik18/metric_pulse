"""
Unit tests for decomposition module.
"""

import pytest
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from decomposition.decomposer import calculate_contribution


class TestCalculateContribution:
    """Tests for contribution calculation."""

    def test_basic_contribution(self):
        """Test basic contribution calculation."""
        df = pd.DataFrame({
            'segment': ['A', 'B', 'C'],
            'current_value': [100, 200, 300],
            'previous_value': [80, 180, 320]
        })
        
        result = calculate_contribution(df)
        
        assert 'change' in result.columns
        assert 'contribution_pct' in result.columns
        assert len(result) == 3

    def test_contribution_sums_to_100(self):
        """Test that contributions sum to approximately 100%."""
        df = pd.DataFrame({
            'segment': ['A', 'B'],
            'current_value': [150, 250],
            'previous_value': [100, 200]
        })
        
        result = calculate_contribution(df)
        total_contribution = result['contribution_pct'].sum()
        
        assert abs(total_contribution - 100) < 0.1

    def test_negative_change(self):
        """Test handling of negative changes."""
        df = pd.DataFrame({
            'segment': ['A', 'B'],
            'current_value': [50, 100],
            'previous_value': [100, 200]
        })
        
        result = calculate_contribution(df)
        
        assert all(result['change'] < 0)

    def test_zero_previous_value(self):
        """Test handling of zero previous values."""
        df = pd.DataFrame({
            'segment': ['A', 'B'],
            'current_value': [100, 200],
            'previous_value': [0, 100]
        })
        
        result = calculate_contribution(df)
        
        # Should not raise errors
        assert len(result) == 2
