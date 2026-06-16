"""
Execute Redshift schema and table setup.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.db import get_connection
from config.logging_config import setup_logger

logger = setup_logger(__name__)


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

    statements = [s.strip() for s in sql_content.split(';') if s.strip() and not s.strip().startswith('--')]

    logger.info(f"Found {len(statements)} SQL statements to execute")

    conn = get_connection()
    logger.info("Connected to Redshift")
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
    """Verify tables were created in raw_data schema."""
    conn = get_connection()
    cursor = conn.cursor()

    query = """
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE schemaname = 'raw_data'
        ORDER BY tablename;
    """

    cursor.execute(query)
    tables = cursor.fetchall()

    cursor.close()
    conn.close()

    logger.info(f"Found {len(tables)} tables in raw_data schema")
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
