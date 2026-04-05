{{ config(materialized='table') }}

WITH order_details AS (
    SELECT
        o.order_id,
        o.order_date,
        p.product_category,
        dp.product_category_group,
        oi.total_item_value
    FROM {{ ref('stg_orders') }} o
    INNER JOIN {{ ref('stg_order_items') }} oi ON o.order_id = oi.order_id
    INNER JOIN {{ ref('stg_products') }} p ON oi.product_id = p.product_id
    INNER JOIN {{ ref('dim_product') }} dp ON p.product_category = dp.product_category
    WHERE o.order_status NOT IN ('canceled', 'unavailable')
)

SELECT
    order_date AS metric_date,
    product_category,
    product_category_group,
    COUNT(DISTINCT order_id) AS order_count,
    ROUND(SUM(total_item_value), 2) AS total_revenue,
    ROUND(AVG(total_item_value), 2) AS avg_item_value
FROM order_details
GROUP BY order_date, product_category, product_category_group
ORDER BY order_date, total_revenue DESC
