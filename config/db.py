"""
Shared Redshift connection factory used across all pipeline modules.
"""

import os

import redshift_connector
from dotenv import load_dotenv

load_dotenv()


def get_connection() -> redshift_connector.Connection:
    """
    Create and return a Redshift connection using environment variables.

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
