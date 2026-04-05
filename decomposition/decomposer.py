"""
Decompose metric changes by dimension to identify root causes.
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import redshift_connector
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.logging_config import setup_logger

load_dotenv()

logger = setup_logger(__name__)


DIMENSION_TABLES = {
    'geography': {
        'table': 'staging.metric_by_geography',
        'segment_col': 'region',
        'detail_col': 'state_code'
    },
    'product': {
        'table': 'staging.metric_by_product',
        'segment_col': 'product_category_group',
        'detail_col': 'product_category'
    },
    'payment': {
        'table': 'staging.metric_by_payment',
        'segment_col': 'payment_type_display',
        'detail_col': 'payment_type'
    }
}


def get_connection():
    """Create Redshift connection."""
    try:
        conn = redshift_connector.connect(
            host=os.getenv('REDSHIFT_HOST'),
            port=int(os.getenv('REDSHIFT_PORT', 5439)),
            database=os.getenv('REDSHIFT_DATABASE'),
            user=os.getenv('REDSHIFT_USER'),
            password=os.getenv('REDSHIFT_PASSWORD')
        )
        return conn
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        raise


def fetch_dimension_metrics(
    dimension: str,
    current_date: str,
    previous_date: str,
    metric_col: str = 'total_revenue'
) -> pd.DataFrame:
    """
    Fetch metrics for a dimension comparing two dates.
    
    Args:
        dimension: Dimension name (geography, product, payment)
        current_date: Date to analyze
        previous_date: Comparison date
        metric_col: Metric column to compare
    
    Returns:
        DataFrame with current and previous values by segment
    """
    config = DIMENSION_TABLES.get(dimension)
    if not config:
        raise ValueError(f"Unknown dimension: {dimension}")
    
    query = f"""
        WITH current_day AS (
            SELECT 
                {config['segment_col']} AS segment,
                SUM({metric_col}) AS current_value
            FROM {config['table']}
            WHERE metric_date = '{current_date}'
            GROUP BY {config['segment_col']}
        ),
        previous_day AS (
            SELECT 
                {config['segment_col']} AS segment,
                SUM({metric_col}) AS previous_value
            FROM {config['table']}
            WHERE metric_date = '{previous_date}'
            GROUP BY {config['segment_col']}
        )
        SELECT 
            COALESCE(c.segment, p.segment) AS segment,
            COALESCE(c.current_value, 0) AS current_value,
            COALESCE(p.previous_value, 0) AS previous_value
        FROM current_day c
        FULL OUTER JOIN previous_day p ON c.segment = p.segment
        ORDER BY current_value DESC
    """
    
    conn = get_connection()
    
    try:
        df = pd.read_sql(query, conn)
        logger.debug(f"Fetched {len(df)} segments for {dimension}")
        return df
    except Exception as e:
        logger.error(f"Failed to fetch {dimension} metrics: {e}")
        raise
    finally:
        conn.close()


def calculate_contribution(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate each segment's contribution to total change.
    
    Args:
        df: DataFrame with current_value and previous_value
    
    Returns:
        DataFrame with contribution metrics
    """
    df = df.copy()
    
    # Calculate changes
    df['change'] = df['current_value'] - df['previous_value']
    df['change_pct'] = ((df['change'] / df['previous_value']) * 100).round(2)
    df['change_pct'] = df['change_pct'].fillna(0).replace([float('inf'), float('-inf')], 0)
    
    # Calculate total change
    total_change = df['change'].sum()
    
    # Calculate contribution to total change
    if total_change != 0:
        df['contribution_pct'] = ((df['change'] / total_change) * 100).round(2)
    else:
        df['contribution_pct'] = 0
    
    # Absolute contribution for ranking
    df['abs_contribution'] = df['contribution_pct'].abs()
    
    # Sort by absolute contribution
    df = df.sort_values('abs_contribution', ascending=False)
    
    return df


def decompose_metric(
    current_date: str,
    previous_date: str,
    metric_col: str = 'total_revenue'
) -> Dict:
    """
    Decompose metric change across all dimensions.
    
    Args:
        current_date: Date to analyze
        previous_date: Comparison date
        metric_col: Metric to decompose
    
    Returns:
        Dictionary with decomposition results
    """
    logger.info(f"Decomposing {metric_col}: {previous_date} → {current_date}")
    
    results = {
        'current_date': current_date,
        'previous_date': previous_date,
        'metric': metric_col,
        'dimensions': {}
    }
    
    for dimension in DIMENSION_TABLES.keys():
        try:
            # Fetch data
            df = fetch_dimension_metrics(dimension, current_date, previous_date, metric_col)
            
            if df.empty:
                logger.warning(f"No data for {dimension}")
                continue
            
            # Calculate contributions
            df_analyzed = calculate_contribution(df)
            
            # Get top contributors
            top_contributors = df_analyzed.head(5).to_dict('records')
            
            # Summary stats
            total_current = df_analyzed['current_value'].sum()
            total_previous = df_analyzed['previous_value'].sum()
            total_change = total_current - total_previous
            total_change_pct = ((total_change / total_previous) * 100) if total_previous else 0
            
            results['dimensions'][dimension] = {
                'total_current': round(total_current, 2),
                'total_previous': round(total_previous, 2),
                'total_change': round(total_change, 2),
                'total_change_pct': round(total_change_pct, 2),
                'top_contributors': top_contributors,
                'segment_count': len(df_analyzed)
            }
            
            logger.info(f"{dimension}: {total_change_pct:+.2f}% change, top driver: {top_contributors[0]['segment'] if top_contributors else 'N/A'}")
            
        except Exception as e:
            logger.error(f"Failed to decompose {dimension}: {e}")
            results['dimensions'][dimension] = {'error': str(e)}
    
    return results


def get_top_driver(results: Dict) -> Dict:
    """
    Identify the single biggest driver across all dimensions.
    
    Args:
        results: Decomposition results
    
    Returns:
        Dictionary with top driver info
    """
    top_driver = None
    max_contribution = 0
    
    for dim_name, dim_data in results['dimensions'].items():
        if 'error' in dim_data:
            continue
            
        for contributor in dim_data.get('top_contributors', []):
            if contributor['abs_contribution'] > max_contribution:
                max_contribution = contributor['abs_contribution']
                top_driver = {
                    'dimension': dim_name,
                    'segment': contributor['segment'],
                    'contribution_pct': contributor['contribution_pct'],
                    'change': contributor['change'],
                    'change_pct': contributor['change_pct']
                }
    
    return top_driver


def get_comparison_dates(target_date: str = None) -> tuple:
    """
    Get current and previous date for comparison.
    
    If no target date provided, uses the latest date in the data.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    if target_date:
        query = f"""
            SELECT DISTINCT metric_date 
            FROM staging.fact_daily_metrics 
            WHERE metric_date <= '{target_date}'
            ORDER BY metric_date DESC 
            LIMIT 2
        """
    else:
        query = """
            SELECT DISTINCT metric_date 
            FROM staging.fact_daily_metrics 
            ORDER BY metric_date DESC 
            LIMIT 2
        """
    
    cursor.execute(query)
    dates = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    if len(dates) < 2:
        raise ValueError("Not enough dates for comparison")
    
    current_date = str(dates[0][0])
    previous_date = str(dates[1][0])
    
    return current_date, previous_date


if __name__ == "__main__":
    logger.info("Starting metric decomposition")
    
    try:
        # Get dates
        current_date, previous_date = get_comparison_dates()
        
        # Run decomposition
        results = decompose_metric(current_date, previous_date)
        
        # Get top driver
        top_driver = get_top_driver(results)
        
        print("\n" + "=" * 60)
        print("METRIC DECOMPOSITION RESULTS")
        print("=" * 60)
        print(f"Comparing: {previous_date} → {current_date}")
        
        for dim_name, dim_data in results['dimensions'].items():
            if 'error' in dim_data:
                print(f"\n{dim_name.upper()}: Error - {dim_data['error']}")
                continue
                
            print(f"\n{dim_name.upper()}")
            print(f"  Total change: ${dim_data['total_change']:+,.2f} ({dim_data['total_change_pct']:+.2f}%)")
            print(f"  Top contributors:")
            
            for c in dim_data['top_contributors'][:3]:
                print(f"    • {c['segment']}: {c['contribution_pct']:+.1f}% of change (${c['change']:+,.2f})")
        
        if top_driver:
            print("\n" + "-" * 60)
            print("TOP DRIVER:")
            print(f"  {top_driver['dimension'].upper()} → {top_driver['segment']}")
            print(f"  Contributed {top_driver['contribution_pct']:+.1f}% of total change")
            print(f"  Segment changed {top_driver['change_pct']:+.1f}% (${top_driver['change']:+,.2f})")
        
    except Exception as e:
        logger.error(f"Decomposition failed: {e}")
        sys.exit(1)
