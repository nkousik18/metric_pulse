-- ============================================
-- METRIC PULSE: Redshift Schema Setup
-- ============================================

-- Create schemas
CREATE SCHEMA IF NOT EXISTS raw_data;

CREATE SCHEMA IF NOT EXISTS staging;

CREATE SCHEMA IF NOT EXISTS marts;

-- Orders
CREATE TABLE IF NOT EXISTS raw_data.orders (
    order_id VARCHAR(50),
    customer_id VARCHAR(50),
    order_status VARCHAR(20),
    order_purchase_timestamp TIMESTAMP,
    order_approved_at TIMESTAMP,
    order_delivered_carrier_date TIMESTAMP,
    order_delivered_customer_date TIMESTAMP,
    order_estimated_delivery_date TIMESTAMP
);

-- Order Items
CREATE TABLE IF NOT EXISTS raw_data.order_items (
    order_id VARCHAR(50),
    order_item_id INTEGER,
    product_id VARCHAR(50),
    seller_id VARCHAR(50),
    shipping_limit_date TIMESTAMP,
    price DECIMAL(10,2),
    freight_value DECIMAL(10,2)
);

-- Customers
CREATE TABLE IF NOT EXISTS raw_data.customers (
    customer_id VARCHAR(50),
    customer_unique_id VARCHAR(50),
    customer_zip_code_prefix VARCHAR(10),
    customer_city VARCHAR(100),
    customer_state VARCHAR(5)
);

-- Products
CREATE TABLE IF NOT EXISTS raw_data.products (
    product_id VARCHAR(50),
    product_category_name VARCHAR(100),
    product_name_length INTEGER,
    product_description_length INTEGER,
    product_photos_qty INTEGER,
    product_weight_g INTEGER,
    product_length_cm INTEGER,
    product_height_cm INTEGER,
    product_width_cm INTEGER
);

-- Sellers
CREATE TABLE IF NOT EXISTS raw_data.sellers (
    seller_id VARCHAR(50),
    seller_zip_code_prefix VARCHAR(10),
    seller_city VARCHAR(100),
    seller_state VARCHAR(5)
);

-- Payments
CREATE TABLE IF NOT EXISTS raw_data.payments (
    order_id VARCHAR(50),
    payment_sequential INTEGER,
    payment_type VARCHAR(20),
    payment_installments INTEGER,
    payment_value DECIMAL(10,2)
);

-- Category Translation
CREATE TABLE IF NOT EXISTS raw_data.category_translation (
    product_category_name VARCHAR(100),
    product_category_name_english VARCHAR(100)
);
