"""
Shared warehouse connection factory used across all pipeline modules.

Two backends (docs/local-stack-scope.md §6.1):
- duckdb   (default, active): the local file data/warehouse.duckdb, built by
           `python -m ingestion.load_local` + `dbt build --target local`.
- redshift (archived AWS backend): the original Redshift Serverless
           connection, kept byte-for-byte as it was (rule R1: never delete AWS
           code). Selected with WAREHOUSE=redshift, and the default inside Lambda.

Every caller of get_connection() only reads, so the DuckDB connection is opened
read-only. That lets the dashboard and a CLI run read at the same time. DuckDB
allows a single writer, so `dbt build` / `load_local` can't run while a reader
holds the file.
"""

import os

import redshift_connector
from dotenv import load_dotenv

load_dotenv()

BACKENDS = ('duckdb', 'redshift')


def get_connection():
    """
    Return a DB-API connection to the configured warehouse (WAREHOUSE setting).

    Both backends support what the pipeline uses: pd.read_sql(query, conn),
    conn.cursor(), conn.close(). That parity was verified in Phase 2 M6 and again
    for the local stack.
    """
    from config import settings

    return connection_factory(settings.WAREHOUSE)()


def connection_factory(backend: str):
    """The zero-argument connection function for a backend. Split out so the dispatch is
    testable without opening a connection (local-stack scope LS6: the Redshift path can't be
    run live any more, but which code path gets selected can still be checked)."""
    from config import settings

    if backend == 'duckdb':
        return lambda: _duckdb_connection(settings.WAREHOUSE_PATH)
    if backend == 'redshift':
        return _redshift_connection
    raise ValueError(f"WAREHOUSE must be one of {BACKENDS}, got {backend!r}")


def _duckdb_connection(path, read_only: bool = True):
    import duckdb

    if not os.path.exists(path):
        raise RuntimeError(
            f"Local warehouse not found at {path}. Build it first:\n"
            f"  python -m ingestion.load_local\n"
            f"  cd dbt_project && dbt build --target local --profiles-dir ."
        )
    try:
        return duckdb.connect(str(path), read_only=read_only)
    except duckdb.IOException as e:
        raise RuntimeError(
            f"Could not open {path} ({e}). DuckDB allows one writer at a time: stop any running "
            f"`dbt build` / `load_local` and retry."
        ) from e


def _redshift_connection() -> redshift_connector.Connection:
    """
    Archived AWS backend. Create and return a Redshift connection using environment variables.

    Reads REDSHIFT_HOST, REDSHIFT_PORT, REDSHIFT_DATABASE, REDSHIFT_USER,
    REDSHIFT_PASSWORD from the environment (via .env or shell exports).
    """
    try:
        conn = redshift_connector.connect(
            host=os.getenv('REDSHIFT_HOST'),
            port=int(os.getenv('REDSHIFT_PORT', 5439)),
            database=os.getenv('REDSHIFT_DATABASE', 'dev'),
            user=os.getenv('REDSHIFT_USER'),
            password=os.getenv('REDSHIFT_PASSWORD'),
        )
        return conn
    except Exception as e:
        raise RuntimeError(f"Redshift connection failed: {e}") from e


def build_copy_credentials() -> str:
    """
    Return the credentials clause for a Redshift COPY command.

    Prefers an IAM role (REDSHIFT_IAM_ROLE env var) — credentials never
    appear in query text when a role is used.  Falls back to static
    ACCESS_KEY_ID / SECRET_ACCESS_KEY when no role is configured.
    """
    iam_role = os.getenv('REDSHIFT_IAM_ROLE')
    if iam_role:
        return f"IAM_ROLE '{iam_role}'"

    access_key = os.getenv('AWS_ACCESS_KEY_ID')
    secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')

    if not access_key or not secret_key:
        raise ValueError(
            "No Redshift credentials found. "
            "Set REDSHIFT_IAM_ROLE, or both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY."
        )

    return f"ACCESS_KEY_ID '{access_key}'\n        SECRET_ACCESS_KEY '{secret_key}'"
