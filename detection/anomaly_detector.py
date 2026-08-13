"""
Anomaly detection for daily metrics using z-score method.
"""

import os
import sys
from pathlib import Path
from typing import Callable, List, Optional

import pandas as pd
import numpy as np
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.db import get_connection
from config.logging_config import setup_logger

load_dotenv()

logger = setup_logger(__name__)


def fetch_daily_metrics(
    lookback_days: int = 30,
    metric_columns: Optional[List[str]] = None,
    table_name: str = 'staging.fact_daily_metrics',
    connection_factory: Callable = get_connection
) -> pd.DataFrame:
    """
    Fetch daily metrics from Redshift.

    Args:
        lookback_days: Number of days to fetch
        metric_columns: Columns to select alongside metric_date (defaults to Olist's
            order_count/customer_count/total_revenue/avg_order_value; an onboarded dataset
            passes its own classified metric_columns plus row_count -- see onboarding/codegen.py)
        table_name: Fact table to query (see decomposition.decomposer.get_comparison_dates)
        connection_factory: Callable returning a DB connection (see decomposition.decomposer)

    Returns:
        DataFrame with daily metrics
    """
    if metric_columns is None:
        metric_columns = ['order_count', 'customer_count', 'total_revenue', 'avg_order_value']

    query = f"""
        SELECT
            metric_date,
            {', '.join(metric_columns)}
        FROM {table_name}
        ORDER BY metric_date DESC
        LIMIT {lookback_days}
    """

    conn = connection_factory()

    try:
        df = pd.read_sql(query, conn)
        logger.info(f"Fetched {len(df)} days of metrics")
        return df
    except Exception as e:
        logger.error(f"Failed to fetch metrics: {e}")
        raise
    finally:
        conn.close()


def calculate_zscore(series: pd.Series) -> pd.Series:
    """Calculate z-scores for a series."""
    return (series - series.mean()) / series.std()


def detect_anomalies(
    df: pd.DataFrame,
    metric_column: str = 'total_revenue',
    threshold: float = None
) -> pd.DataFrame:
    """
    Detect anomalies in metrics using z-score method.
    
    Args:
        df: DataFrame with metrics
        metric_column: Column to analyze
        threshold: Z-score threshold (default from env)
    
    Returns:
        DataFrame with anomaly flags
    """
    if threshold is None:
        threshold = float(os.getenv('ANOMALY_THRESHOLD_ZSCORE', 2.0))
    
    df = df.copy()
    df = df.sort_values('metric_date')
    
    # Calculate z-scores
    df['zscore'] = calculate_zscore(df[metric_column])
    
    # Flag anomalies
    df['is_anomaly'] = df['zscore'].abs() > threshold
    df['anomaly_direction'] = np.where(
        df['zscore'] > threshold, 'high',
        np.where(df['zscore'] < -threshold, 'low', 'normal')
    )
    
    # Calculate day-over-day change
    df['prev_value'] = df[metric_column].shift(1)
    df['change_value'] = df[metric_column] - df['prev_value']
    df['change_pct'] = (df['change_value'] / df['prev_value'] * 100).round(2)
    
    anomaly_count = df['is_anomaly'].sum()
    logger.info(f"Detected {anomaly_count} anomalies in {metric_column} (threshold: {threshold})")
    
    return df


def get_latest_anomaly(df: pd.DataFrame, metric_col: str = 'total_revenue') -> Optional[dict]:
    """
    Get the most recent anomaly if it exists.

    Args:
        df: Output of detect_anomalies()
        metric_col: The metric column that was analyzed

    Returns:
        Dictionary with anomaly details or None
    """
    anomalies = df[df['is_anomaly'] == True].sort_values('metric_date', ascending=False)

    if anomalies.empty:
        logger.info("No anomalies detected in recent data")
        return None

    latest = anomalies.iloc[0]

    anomaly_info = {
        'metric_date': latest['metric_date'],
        'metric_value': latest[metric_col],
        'zscore': round(latest['zscore'], 2),
        'direction': latest['anomaly_direction'],
        'change_pct': latest['change_pct'],
        'change_value': latest['change_value']
    }

    logger.info(f"Latest anomaly: {anomaly_info['metric_date']} - {anomaly_info['direction']} ({anomaly_info['change_pct']}%)")

    return anomaly_info


def run_detection(
    metric: str = 'total_revenue',
    lookback_days: int = None,
    threshold: float = None,
    metric_columns: Optional[List[str]] = None,
    table_name: str = 'staging.fact_daily_metrics',
    connection_factory: Callable = get_connection
) -> dict:
    """
    Run full anomaly detection pipeline.

    Args:
        metric: Metric column to analyze
        lookback_days: Days to analyze
        threshold: Z-score threshold
        metric_columns: Passed through to fetch_daily_metrics (see its docstring)
        table_name: Passed through to fetch_daily_metrics
        connection_factory: Passed through to fetch_daily_metrics

    Returns:
        Dictionary with detection results
    """
    if lookback_days is None:
        lookback_days = int(os.getenv('LOOKBACK_DAYS', 30))

    logger.info(f"Running anomaly detection: metric={metric}, lookback={lookback_days} days")

    # Fetch data
    df = fetch_daily_metrics(lookback_days, metric_columns, table_name, connection_factory)


    if df.empty:
        logger.warning("No data returned from query")
        return {'status': 'no_data', 'anomalies': []}
    
    # Detect anomalies
    df_analyzed = detect_anomalies(df, metric, threshold)
    
    # Get latest anomaly
    latest_anomaly = get_latest_anomaly(df_analyzed, metric)
    
    # Get all anomalies
    all_anomalies = df_analyzed[df_analyzed['is_anomaly'] == True].to_dict('records')
    
    results = {
        'status': 'completed',
        'metric': metric,
        'lookback_days': lookback_days,
        'total_days_analyzed': len(df),
        'anomaly_count': len(all_anomalies),
        'latest_anomaly': latest_anomaly,
        'all_anomalies': all_anomalies,
        'statistics': {
            'mean': round(df[metric].mean(), 2),
            'std': round(df[metric].std(), 2),
            'min': round(df[metric].min(), 2),
            'max': round(df[metric].max(), 2)
        }
    }
    
    return results


if __name__ == "__main__":
    logger.info("Starting anomaly detection")
    
    try:
        results = run_detection()
        
        print("\n" + "=" * 50)
        print("ANOMALY DETECTION RESULTS")
        print("=" * 50)
        print(f"Metric: {results['metric']}")
        print(f"Days analyzed: {results['total_days_analyzed']}")
        print(f"Anomalies found: {results['anomaly_count']}")
        
        print(f"\nStatistics:")
        print(f"  Mean: ${results['statistics']['mean']:,.2f}")
        print(f"  Std:  ${results['statistics']['std']:,.2f}")
        print(f"  Min:  ${results['statistics']['min']:,.2f}")
        print(f"  Max:  ${results['statistics']['max']:,.2f}")
        
        if results['latest_anomaly']:
            a = results['latest_anomaly']
            print(f"\nLatest Anomaly:")
            print(f"  Date: {a['metric_date']}")
            print(f"  Value: ${a['metric_value']:,.2f}")
            print(f"  Z-score: {a['zscore']}")
            print(f"  Direction: {a['direction']}")
            print(f"  Change: {a['change_pct']}%")
        else:
            print("\nNo anomalies detected in recent data")
            
    except Exception as e:
        logger.error(f"Detection failed: {e}")
        sys.exit(1)
