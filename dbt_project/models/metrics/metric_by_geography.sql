{{ config(materialized='table') }}

WITH order_details AS (
    SELECT
        o.order_id,
        o.order_date,
        c.customer_state,
        g.region,
        oi.total_item_value
    FROM {{ ref('stg_orders') }} o
    INNER JOIN {{ ref('stg_order_items') }} oi ON o.order_id = oi.order_id
    INNER JOIN {{ ref('stg_customers') }} c ON o.customer_id = c.customer_id
    INNER JOIN {{ ref('dim_geography') }} g ON c.customer_state = g.state_code
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
)

SELECT
    order_date AS metric_date,
    customer_state AS state_code,
    region,
    COUNT(DISTINCT order_id) AS order_count,
    ROUND(SUM(total_item_value), 2) AS total_revenue,
    ROUND(AVG(total_item_value), 2) AS avg_item_value
FROM order_details
GROUP BY order_date, customer_state, region
ORDER BY order_date, total_revenue DESC
