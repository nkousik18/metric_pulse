import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

# AWS Configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# S3 Configuration
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "metric-pulse-data")
S3_RAW_PREFIX = "raw/"
S3_PROCESSED_PREFIX = "processed/"

# Redshift Configuration
REDSHIFT_HOST = os.getenv("REDSHIFT_HOST")
REDSHIFT_PORT = int(os.getenv("REDSHIFT_PORT", 5439))
REDSHIFT_DATABASE = os.getenv("REDSHIFT_DATABASE", "dev")
REDSHIFT_USER = os.getenv("REDSHIFT_USER")
REDSHIFT_PASSWORD = os.getenv("REDSHIFT_PASSWORD")
REDSHIFT_SCHEMA_RAW = "raw"
REDSHIFT_SCHEMA_STAGING = "staging"
REDSHIFT_SCHEMA_MARTS = "marts"

# SNS Configuration
SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN")

# Detection Configuration
ANOMALY_THRESHOLD_ZSCORE = float(os.getenv("ANOMALY_THRESHOLD_ZSCORE", 2.0))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", 30))