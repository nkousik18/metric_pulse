{{ config(materialized='view') }}

SELECT
    order_id,
    customer_id,
    order_status,
    order_purchase_timestamp,
    DATE(order_purchase_timestamp) AS order_date,
    DATE_PART(year, order_purchase_timestamp) AS order_year,
    DATE_PART(month, order_purchase_timestamp) AS order_month,
    DATE_PART(dow, order_purchase_timestamp) AS order_day_of_week,
    order_approved_at,
    order_delivered_carrier_date,
    order_delivered_customer_date,
    order_estimated_delivery_date,
    DATEDIFF(day, order_purchase_timestamp, order_delivered_customer_date) AS delivery_days
FROM {{ source('raw_data', 'orders') }}
WHERE order_purchase_timestamp IS NOT NULL
