{{ config(materialized='table') }}

WITH order_revenue AS (
    SELECT
        o.order_id,
        o.order_date,
        o.customer_id,
        o.order_status,
        SUM(oi.total_item_value) AS order_revenue
    FROM {{ ref('stg_orders') }} o
    INNER JOIN {{ ref('stg_order_items') }} oi ON o.order_id = oi.order_id
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
    GROUP BY o.order_id, o.order_date, o.customer_id, o.order_status
),

daily_metrics AS (
    SELECT
        order_date AS metric_date,
        COUNT(DISTINCT order_id) AS order_count,
        COUNT(DISTINCT customer_id) AS customer_count,
        SUM(order_revenue) AS total_revenue,
        AVG(order_revenue) AS avg_order_value,
        MIN(order_revenue) AS min_order_value,
        MAX(order_revenue) AS max_order_value
    FROM order_revenue
    GROUP BY order_date
)

SELECT
    metric_date,
    order_count,
    customer_count,
    ROUND(total_revenue, 2) AS total_revenue,
    ROUND(avg_order_value, 2) AS avg_order_value,
    ROUND(min_order_value, 2) AS min_order_value,
    ROUND(max_order_value, 2) AS max_order_value,
    DATE_PART(year, metric_date) AS metric_year,
    DATE_PART(month, metric_date) AS metric_month,
    DATE_PART(dow, metric_date) AS day_of_week
FROM daily_metrics
ORDER BY metric_date
