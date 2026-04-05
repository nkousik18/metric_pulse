-- Test that total revenue is never negative
SELECT metric_date, total_revenue
FROM {{ ref('fact_daily_metrics') }}
WHERE total_revenue < 0
