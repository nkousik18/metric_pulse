-- Test for large gaps in date coverage (flags gaps > 30 days)
{{ config(severity = 'warn') }}

WITH date_gaps AS (
    SELECT 
        metric_date,
        LAG(metric_date) OVER (ORDER BY metric_date) AS prev_date,
        {{ dbt.datediff('LAG(metric_date) OVER (ORDER BY metric_date)', 'metric_date', 'day') }} AS gap_days
    FROM {{ ref('fact_daily_metrics') }}
)
SELECT *
FROM date_gaps
WHERE gap_days > 30