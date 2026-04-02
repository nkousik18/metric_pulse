{{ config(materialized='table') }}

SELECT DISTINCT
    product_category,
    CASE
        WHEN product_category IN ('computers_accessories', 'electronics', 'computers', 'tablets_printing_image', 'telephony', 'consoles_games') THEN 'Electronics'
        WHEN product_category IN ('furniture_decor', 'furniture_living_room', 'furniture_bedroom', 'furniture_mattress_and_upholstery', 'office_furniture', 'bed_bath_table', 'home_comfort', 'home_comfort_2', 'home_confort') THEN 'Home & Furniture'
        WHEN product_category IN ('sports_leisure', 'fashion_bags_accessories', 'fashion_shoes', 'fashion_sport', 'fashion_underwear_beach', 'fashion_male_clothing', 'fashion_female_clothing', 'fashion_childrens_clothes') THEN 'Fashion & Sports'
        WHEN product_category IN ('health_beauty', 'perfumery', 'diapers_and_hygiene') THEN 'Health & Beauty'
        WHEN product_category IN ('toys', 'baby', 'cool_stuff') THEN 'Kids & Toys'
        WHEN product_category IN ('auto', 'garden_tools', 'construction_tools_construction', 'construction_tools_safety', 'construction_tools_lights') THEN 'Auto & Tools'
        ELSE 'Other'
    END AS product_category_group
FROM {{ ref('stg_products') }}
WHERE product_category IS NOT NULL
