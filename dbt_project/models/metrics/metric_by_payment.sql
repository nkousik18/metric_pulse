{{ config(materialized='table') }}

WITH order_revenue AS (
    -- Aggregate to order level first to avoid row multiplication
    -- when joining items (N rows) × payments (M rows) below
    SELECT
        order_id,
        SUM(total_item_value) AS order_revenue
    FROM {{ ref('stg_order_items') }}
    GROUP BY order_id
),

primary_payment AS (
    -- payment_sequential = 1 is the primary (or only) payment for each order
    SELECT
        order_id,
        payment_type
    FROM {{ source('raw_data', 'payments') }}
    WHERE payment_sequential = 1
),

order_details AS (
    SELECT
        o.order_id,
        o.order_date,
        pp.payment_type,
        dp.payment_type_display,
        r.order_revenue
    FROM {{ ref('stg_orders') }} o
    INNER JOIN order_revenue r ON o.order_id = r.order_id
    INNER JOIN primary_payment pp ON o.order_id = pp.order_id
    INNER JOIN {{ ref('dim_payment') }} dp ON pp.payment_type = dp.payment_type
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
)

SELECT
    order_date AS metric_date,
    payment_type,
    payment_type_display,
    COUNT(DISTINCT order_id) AS order_count,
    ROUND(SUM(order_revenue), 2) AS total_revenue,
    ROUND(AVG(order_revenue), 2) AS avg_order_value
FROM order_details
GROUP BY order_date, payment_type, payment_type_display
ORDER BY order_date, total_revenue DESC
