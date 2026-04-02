"""
Execute Redshift schema and table setup.
"""

import os
import sys
from pathlib import Path

import redshift_connector
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.logging_config import setup_logger

load_dotenv()

logger = setup_logger(__name__)


def get_connection():
    """Create Redshift connection."""
    try:
        conn = redshift_connector.connect(
            host=os.getenv('REDSHIFT_HOST'),
            port=int(os.getenv('REDSHIFT_PORT', 5439)),
            database=os.getenv('REDSHIFT_DATABASE'),
            user=os.getenv('REDSHIFT_USER'),
            password=os.getenv('REDSHIFT_PASSWORD')
        )
        logger.info("Connected to Redshift")
        return conn
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        raise


def execute_sql_file(sql_file: str):
    """
    Execute SQL file against Redshift.
    
    Args:
        sql_file: Path to SQL file
    """
    sql_path = Path(__file__).parent.parent / sql_file
    
    if not sql_path.exists():
        logger.error(f"SQL file not found: {sql_path}")
        raise FileNotFoundError(f"SQL file not found: {sql_path}")
    
    logger.info(f"Reading SQL from {sql_path}")
    
    with open(sql_path, 'r') as f:
        sql_content = f.read()
    
    # Split by semicolon, filter empty statements
    statements = [s.strip() for s in sql_content.split(';') if s.strip() and not s.strip().startswith('--')]
    
    logger.info(f"Found {len(statements)} SQL statements to execute")
    
    conn = get_connection()
    cursor = conn.cursor()
    
    success_count = 0
    error_count = 0
    
    for i, statement in enumerate(statements, 1):
        # Skip comment-only statements
        if all(line.strip().startswith('--') or not line.strip() for line in statement.split('\n')):
            continue
            
        try:
            # Log first 80 chars of statement
            preview = statement.replace('\n', ' ')[:80]
            logger.debug(f"Executing [{i}/{len(statements)}]: {preview}...")
            
            cursor.execute(statement)
            conn.commit()
            success_count += 1
            
        except Exception as e:
            error_count += 1
            logger.error(f"Statement {i} failed: {e}")
            logger.error(f"Statement: {statement[:200]}")
            conn.rollback()
    
    cursor.close()
    conn.close()
    
    logger.info(f"Execution complete: {success_count} succeeded, {error_count} failed")
    
    return {"success": success_count, "errors": error_count}


def verify_tables():
    """Verify tables were created."""
    conn = get_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT schemaname, tablename 
        FROM pg_tables 
        WHERE schemaname IN ('raw', 'staging', 'marts')
        ORDER BY schemaname, tablename;
    """
    
    cursor.execute(query)
    tables = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    logger.info(f"Found {len(tables)} tables in project schemas")
    
    for schema, table in tables:
        logger.info(f"  {schema}.{table}")
    
    return tables


if __name__ == "__main__":
    logger.info("Starting Redshift setup")
    
    try:
        results = execute_sql_file("infrastructure/redshift_setup.sql")
        
        print("\n" + "=" * 50)
        print("SETUP SUMMARY")
        print("=" * 50)
        print(f"Statements executed: {results['success']}")
        print(f"Errors: {results['errors']}")
        
        print("\nVerifying tables...")
        tables = verify_tables()
        
        print(f"\nTables created: {len(tables)}")
        for schema, table in tables:
            print(f"  ✓ {schema}.{table}")
        
    except Exception as e:
        logger.error(f"Setup failed: {e}")
        sys.exit(1)
