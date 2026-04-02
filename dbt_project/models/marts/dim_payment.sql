{{ config(materialized='table') }}

SELECT DISTINCT
    payment_type,
    CASE 
        WHEN payment_type = 'credit_card' THEN 'Credit Card'
        WHEN payment_type = 'boleto' THEN 'Boleto'
        WHEN payment_type = 'voucher' THEN 'Voucher'
        WHEN payment_type = 'debit_card' THEN 'Debit Card'
        ELSE 'Other'
    END AS payment_type_display
FROM {{ source('raw_data', 'payments') }}
WHERE payment_type IS NOT NULL
