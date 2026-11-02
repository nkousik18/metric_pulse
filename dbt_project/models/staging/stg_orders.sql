{{ config(materialized='view') }}

SELECT
    order_id,
    customer_id,
    order_status,
    order_purchase_timestamp,
    DATE(order_purchase_timestamp) AS order_date,
    EXTRACT(year FROM order_purchase_timestamp) AS order_year,
    EXTRACT(month FROM order_purchase_timestamp) AS order_month,
    EXTRACT(dow FROM order_purchase_timestamp) AS order_day_of_week,
    order_approved_at,
    order_delivered_carrier_date,
    order_delivered_customer_date,
    order_estimated_delivery_date,
    {{ dbt.datediff('order_purchase_timestamp', 'order_delivered_customer_date', 'day') }} AS delivery_days
FROM {{ source('raw_data', 'orders') }}
WHERE order_purchase_timestamp IS NOT NULL
