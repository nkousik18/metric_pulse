"""
Unit tests for narrative generation module.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from narrative.generator import format_currency, generate_narrative


class TestFormatCurrency:
    """Tests for currency formatting."""

    def test_basic_formatting(self):
        """Test basic currency format."""
        assert format_currency(1234.56) == "1,234.56"

    def test_large_number(self):
        """Test large number formatting."""
        assert format_currency(1234567.89) == "1,234,567.89"

    def test_none_value(self):
        """Test None handling."""
        assert format_currency(None) == "0.00"

    def test_negative_value(self):
        """Test negative value (returns absolute)."""
        assert format_currency(-100.50) == "100.50"


class TestGenerateNarrative:
    """Tests for narrative generation."""

    def test_generates_all_formats(self):
        """Test that all output formats are generated."""
        mock_results = {
            'current_date': '2024-01-02',
            'previous_date': '2024-01-01',
            'metric': 'total_revenue',
            'dimensions': {
                'geography': {
                    'total_current': 1000,
                    'total_previous': 800,
                    'total_change': 200,
                    'total_change_pct': 25.0,
                    'top_contributors': [
                        {'segment': 'Southeast', 'contribution_pct': 60.0, 'change': 120}
                    ]
                }
            }
        }
        
        narratives = generate_narrative(mock_results)
        
        assert 'full' in narratives
        assert 'slack' in narratives
        assert 'email_subject' in narratives
        assert 'summary' in narratives

    def test_summary_contains_key_info(self):
        """Test summary contains metric and driver."""
        mock_results = {
            'current_date': '2024-01-02',
            'previous_date': '2024-01-01',
            'metric': 'total_revenue',
            'dimensions': {
                'geography': {
                    'total_current': 1000,
                    'total_previous': 800,
                    'total_change': 200,
                    'total_change_pct': 25.0,
                    'top_contributors': [
                        {'segment': 'Southeast', 'contribution_pct': 60.0, 'change': 120}
                    ]
                }
            }
        }
        
        narratives = generate_narrative(mock_results)
        
        assert 'Total Revenue' in narratives['summary']
        assert 'Southeast' in narratives['summary']
