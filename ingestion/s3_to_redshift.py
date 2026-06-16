"""
Load data from S3 into Redshift tables using COPY command.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.db import build_copy_credentials, get_connection
from config.logging_config import setup_logger

load_dotenv()

logger = setup_logger(__name__)

# Mapping of S3 files to Redshift tables
FILE_TABLE_MAPPING = {
    "olist_orders_dataset.csv": "raw_data.orders",
    "olist_order_items_dataset.csv": "raw_data.order_items",
    "olist_customers_dataset.csv": "raw_data.customers",
    "olist_products_dataset.csv": "raw_data.products",
    "olist_sellers_dataset.csv": "raw_data.sellers",
    "olist_order_payments_dataset.csv": "raw_data.payments",
    "product_category_name_translation.csv": "raw_data.category_translation",
}


def truncate_table(cursor, table_name: str):
    """Truncate table before loading."""
    try:
        cursor.execute(f"TRUNCATE TABLE {table_name};")
        logger.info(f"Truncated {table_name}")
    except Exception as e:
        logger.error(f"Failed to truncate {table_name}: {e}")
        raise


def load_table(cursor, s3_file: str, table_name: str) -> int:
    """
    Load a single CSV from S3 into a Redshift table using COPY.

    Credentials are resolved via build_copy_credentials(): IAM role if
    REDSHIFT_IAM_ROLE is set, otherwise ACCESS_KEY_ID / SECRET_ACCESS_KEY.

    Returns:
        Number of rows loaded
    """
    bucket = os.getenv('S3_BUCKET_NAME')
    region = os.getenv('AWS_REGION')
    s3_path = f"s3://{bucket}/raw/{s3_file}"
    credentials = build_copy_credentials()

    copy_sql = f"""
        COPY {table_name}
        FROM '{s3_path}'
        {credentials}
        REGION '{region}'
        CSV
        IGNOREHEADER 1
        DATEFORMAT 'auto'
        TIMEFORMAT 'auto'
        TRUNCATECOLUMNS
        BLANKSASNULL
        EMPTYASNULL;
    """

    try:
        logger.info(f"Loading {s3_file} -> {table_name}")
        cursor.execute(copy_sql)

        cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
        row_count = cursor.fetchone()[0]

        logger.info(f"Loaded {row_count:,} rows into {table_name}")
        return row_count

    except Exception as e:
        logger.error(f"Failed to load {s3_file}: {e}")
        raise


def load_all_tables() -> dict:
    """
    Load all files from S3 to Redshift.

    Returns:
        Dictionary mapping table name -> row count
    """
    results = {}

    conn = get_connection()
    logger.info("Connected to Redshift")
    cursor = conn.cursor()

    try:
        for s3_file, table_name in FILE_TABLE_MAPPING.items():
            truncate_table(cursor, table_name)
            row_count = load_table(cursor, s3_file, table_name)
            conn.commit()
            results[table_name] = row_count

    except Exception as e:
        logger.error(f"Load process failed: {e}")
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()

    return results


def verify_loads() -> dict:
    """Verify row counts in all tables after load."""
    conn = get_connection()
    cursor = conn.cursor()

    counts = {}
    for table_name in FILE_TABLE_MAPPING.values():
        cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
        counts[table_name] = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    return counts


if __name__ == "__main__":
    logger.info("Starting S3 to Redshift data load")
    
    try:
        results = load_all_tables()
        
        print("\n" + "=" * 50)
        print("LOAD SUMMARY")
        print("=" * 50)
        
        total_rows = 0
        for table, count in results.items():
            print(f"  {table}: {count:,} rows")
            total_rows += count
        
        print(f"\nTotal rows loaded: {total_rows:,}")
        
        print("\nVerifying loads...")
        verified = verify_loads()
        
        all_match = all(results[t] == verified[t] for t in results)
        if all_match:
            print("✓ All tables verified successfully")
        else:
            print("✗ Verification mismatch detected")
            
    except Exception as e:
        logger.error(f"Load process failed: {e}")
        sys.exit(1)
