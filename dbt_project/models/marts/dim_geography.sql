{{ config(materialized='table') }}

SELECT DISTINCT
    customer_state AS state_code,
    customer_state AS state_name,
    CASE 
        WHEN customer_state IN ('SP', 'RJ', 'MG', 'ES') THEN 'Southeast'
        WHEN customer_state IN ('PR', 'SC', 'RS') THEN 'South'
        WHEN customer_state IN ('BA', 'SE', 'AL', 'PE', 'PB', 'RN', 'CE', 'PI', 'MA') THEN 'Northeast'
        WHEN customer_state IN ('GO', 'MT', 'MS', 'DF') THEN 'Central-West'
        WHEN customer_state IN ('AM', 'PA', 'AC', 'RO', 'RR', 'AP', 'TO') THEN 'North'
        ELSE 'Unknown'
    END AS region
FROM {{ ref('stg_customers') }}
WHERE customer_state IS NOT NULL
