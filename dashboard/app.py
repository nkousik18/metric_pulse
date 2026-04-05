"""
MetricPulse Streamlit Dashboard
Interactive drill-down interface for metric analysis.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import redshift_connector
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.logging_config import setup_logger

load_dotenv()

logger = setup_logger(__name__)

# Page config
st.set_page_config(
    page_title="MetricPulse",
    page_icon="📊",
    layout="wide"
)


@st.cache_resource
def get_connection():
    """Create cached Redshift connection."""
    return redshift_connector.connect(
        host=os.getenv('REDSHIFT_HOST'),
        port=int(os.getenv('REDSHIFT_PORT', 5439)),
        database=os.getenv('REDSHIFT_DATABASE'),
        user=os.getenv('REDSHIFT_USER'),
        password=os.getenv('REDSHIFT_PASSWORD')
    )


@st.cache_data(ttl=300)
def fetch_daily_metrics():
    """Fetch all daily metrics."""
    query = """
        SELECT * FROM staging.fact_daily_metrics
        ORDER BY metric_date
    """
    conn = get_connection()
    return pd.read_sql(query, conn)


@st.cache_data(ttl=300)
def fetch_metric_by_dimension(dimension: str):
    """Fetch metrics by dimension."""
    table_map = {
        'geography': 'staging.metric_by_geography',
        'product': 'staging.metric_by_product',
        'payment': 'staging.metric_by_payment'
    }
    query = f"SELECT * FROM {table_map[dimension]} ORDER BY metric_date"
    conn = get_connection()
    return pd.read_sql(query, conn)


def calculate_change(df: pd.DataFrame, metric_col: str, current_date, previous_date):
    """Calculate change between two dates."""
    current = df[df['metric_date'] == current_date][metric_col].sum()
    previous = df[df['metric_date'] == previous_date][metric_col].sum()
    change = current - previous
    change_pct = (change / previous * 100) if previous else 0
    return current, previous, change, change_pct


def render_header():
    """Render dashboard header."""
    st.title("📊 MetricPulse")
    st.markdown("*Automated Root Cause Analysis for Metric Movements*")
    st.divider()


def render_date_selector(df: pd.DataFrame):
    """Render date selection controls."""
    dates = sorted(df['metric_date'].unique(), reverse=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        current_date = st.selectbox(
            "Current Date",
            options=dates,
            index=0
        )
    
    with col2:
        # Default to previous available date
        prev_dates = [d for d in dates if d < current_date]
        previous_date = st.selectbox(
            "Compare To",
            options=prev_dates,
            index=0 if prev_dates else None
        )
    
    return current_date, previous_date


def render_kpi_cards(df: pd.DataFrame, current_date, previous_date):
    """Render KPI summary cards."""
    metrics = ['total_revenue', 'order_count', 'avg_order_value']
    labels = ['Total Revenue', 'Order Count', 'Avg Order Value']
    prefixes = ['$', '', '$']
    
    cols = st.columns(len(metrics))
    
    for col, metric, label, prefix in zip(cols, metrics, labels, prefixes):
        current, previous, change, change_pct = calculate_change(
            df, metric, current_date, previous_date
        )
        
        with col:
            st.metric(
                label=label,
                value=f"{prefix}{current:,.2f}" if prefix == '$' else f"{int(current):,}",
                delta=f"{change_pct:+.1f}%"
            )


def render_trend_chart(df: pd.DataFrame, metric: str):
    """Render metric trend chart."""
    fig = px.line(
        df,
        x='metric_date',
        y=metric,
        title=f"{metric.replace('_', ' ').title()} Over Time"
    )
    
    fig.update_layout(
        xaxis_title="Date",
        yaxis_title=metric.replace('_', ' ').title(),
        hovermode='x unified'
    )
    
    st.plotly_chart(fig, use_container_width=True)


def render_decomposition(dimension: str, current_date, previous_date):
    """Render decomposition analysis for a dimension."""
    df = fetch_metric_by_dimension(dimension)
    
    # Get segment column based on dimension
    segment_col = {
        'geography': 'region',
        'product': 'product_category_group',
        'payment': 'payment_type_display'
    }[dimension]
    
    # Aggregate by segment for each date
    current_data = df[df['metric_date'] == current_date].groupby(segment_col)['total_revenue'].sum().reset_index()
    current_data.columns = ['segment', 'current_value']
    
    previous_data = df[df['metric_date'] == previous_date].groupby(segment_col)['total_revenue'].sum().reset_index()
    previous_data.columns = ['segment', 'previous_value']
    
    # Merge and calculate changes
    merged = pd.merge(current_data, previous_data, on='segment', how='outer').fillna(0)
    merged['change'] = merged['current_value'] - merged['previous_value']
    merged['change_pct'] = (merged['change'] / merged['previous_value'] * 100).fillna(0)
    
    total_change = merged['change'].sum()
    merged['contribution'] = (merged['change'] / total_change * 100) if total_change else 0
    merged = merged.sort_values('contribution', ascending=True)
    
    # Waterfall chart
    fig = go.Figure(go.Waterfall(
        name="Contribution",
        orientation="h",
        y=merged['segment'],
        x=merged['change'],
        connector={"line": {"color": "rgb(63, 63, 63)"}},
        text=[f"{c:+.1f}%" for c in merged['contribution']],
        textposition="outside"
    ))
    
    fig.update_layout(
        title=f"Revenue Change by {dimension.title()}",
        xaxis_title="Revenue Change ($)",
        yaxis_title=dimension.title(),
        showlegend=False
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Table view
    with st.expander("View Details"):
        display_df = merged[['segment', 'previous_value', 'current_value', 'change', 'contribution']].copy()
        display_df.columns = ['Segment', 'Previous', 'Current', 'Change', 'Contribution %']
        display_df = display_df.sort_values('Contribution %', ascending=False)
        st.dataframe(display_df, use_container_width=True)


def render_alert_panel(current_date, previous_date, df):
    """Render alert configuration panel."""
    st.subheader("🔔 Alert Configuration")
    
    col1, col2 = st.columns(2)
    
    with col1:
        threshold = st.slider(
            "Z-Score Threshold",
            min_value=1.0,
            max_value=3.0,
            value=2.0,
            step=0.1,
            help="Lower = more sensitive, Higher = fewer alerts"
        )
    
    with col2:
        if st.button("🚀 Run Pipeline Now", type="primary"):
            with st.spinner("Running pipeline..."):
                from orchestration.run_pipeline import run_pipeline
                results = run_pipeline(force_alert=True)
                
                if results['status'] == 'completed':
                    st.success("Pipeline completed! Check your email for the alert.")
                else:
                    st.error(f"Pipeline failed: {results.get('error', 'Unknown error')}")


def main():
    """Main dashboard entry point."""
    render_header()
    
    try:
        # Fetch data
        df = fetch_daily_metrics()
        
        if df.empty:
            st.error("No data available. Please run the dbt models first.")
            return
        
        # Date selection
        current_date, previous_date = render_date_selector(df)
        
        if not previous_date:
            st.warning("Not enough dates for comparison")
            return
        
        # KPI Cards
        st.subheader("📈 Key Metrics")
        render_kpi_cards(df, current_date, previous_date)
        
        st.divider()
        
        # Trend Chart
        metric_choice = st.selectbox(
            "Select Metric",
            options=['total_revenue', 'order_count', 'avg_order_value'],
            format_func=lambda x: x.replace('_', ' ').title()
        )
        render_trend_chart(df, metric_choice)
        
        st.divider()
        
        # Decomposition
        st.subheader("🔍 Root Cause Analysis")
        st.markdown(f"**Analyzing change from {previous_date} to {current_date}**")
        
        tabs = st.tabs(["Geography", "Product", "Payment"])
        
        with tabs[0]:
            render_decomposition('geography', current_date, previous_date)
        
        with tabs[1]:
            render_decomposition('product', current_date, previous_date)
        
        with tabs[2]:
            render_decomposition('payment', current_date, previous_date)
        
        st.divider()
        
        # Alert Panel
        render_alert_panel(current_date, previous_date, df)
        
    except Exception as e:
        st.error(f"Error loading dashboard: {e}")
        logger.error(f"Dashboard error: {e}")


if __name__ == "__main__":
    main()
