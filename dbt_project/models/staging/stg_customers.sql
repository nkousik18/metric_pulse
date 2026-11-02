{{ config(materialized='view') }}

SELECT
    customer_id,
    customer_unique_id,
    customer_city_DOES_NOT_EXIST,
    customer_state,
    customer_zip_code_prefix
FROM {{ source('raw_data', 'customers') }}
