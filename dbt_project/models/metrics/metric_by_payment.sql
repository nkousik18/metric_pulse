{{ config(materialized='table') }}

WITH order_details AS (
    SELECT
        o.order_id,
        o.order_date,
        pay.payment_type,
        dp.payment_type_display,
        oi.total_item_value
    FROM {{ ref('stg_orders') }} o
    INNER JOIN {{ ref('stg_order_items') }} oi ON o.order_id = oi.order_id
    INNER JOIN {{ source('raw_data', 'payments') }} pay ON o.order_id = pay.order_id
    INNER JOIN {{ ref('dim_payment') }} dp ON pay.payment_type = dp.payment_type
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
)

SELECT
    order_date AS metric_date,
    payment_type,
    payment_type_display,
    COUNT(DISTINCT order_id) AS order_count,
    ROUND(SUM(total_item_value), 2) AS total_revenue,
    ROUND(AVG(total_item_value), 2) AS avg_item_value
FROM order_details
GROUP BY order_date, payment_type, payment_type_display
ORDER BY order_date, total_revenue DESC
