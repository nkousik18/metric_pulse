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
REDSHIFT_SCHEMA_RAW = "raw_data"
REDSHIFT_SCHEMA_STAGING = "staging"
REDSHIFT_SCHEMA_MARTS = "marts"

# SNS Configuration
SNS_TOPIC_ARN = os.getenv("SNS_TOPIC_ARN")

# Detection Configuration
ANOMALY_THRESHOLD_ZSCORE = float(os.getenv("ANOMALY_THRESHOLD_ZSCORE", 2.0))
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", 30))

# Investigation Agent Configuration (Phase 1 -- investigation/synthesize node)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
# LangSmith tracing (docs/action-agent-scope.md §13.1). LangChain/LangGraph read the
# LANGSMITH_* variables straight from the environment (load_dotenv above puts .env there);
# these constants mirror them for MetricPulse's own code. Off unless LANGSMITH_TRACING=true.
LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").strip().lower() == "true"
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
os.environ.setdefault("LANGSMITH_PROJECT", "metricpulse")
LANGSMITH_PROJECT = os.environ["LANGSMITH_PROJECT"]

# Action Agent (docs/action-agent-scope.md D5, D8). Local-only SQLite files (D9), gitignored.
ACTIONS_DB_PATH = Path(os.getenv("ACTIONS_DB_PATH", PROJECT_ROOT / "actions.db"))
CHECKPOINTS_DB_PATH = Path(os.getenv("CHECKPOINTS_DB_PATH", PROJECT_ROOT / "checkpoints.db"))
PROPOSAL_TTL_HOURS = 24  # F2
# Single approver identity for the CLI approver (D8). Falls back to the OS user.
ACTION_APPROVER = os.getenv("ACTION_APPROVER")

# Warehouse backend (docs/local-stack-scope.md §6.1, R2). Local DuckDB is the default; Redshift is
# the archived AWS backend, kept intact (R1). Inside AWS Lambda (AWS_LAMBDA_FUNCTION_NAME is set)
# the default stays Redshift, so the archived Lambda image behaves exactly as it always did.


def backend_default(local: str, aws: str, environ=os.environ) -> str:
    """Local backend by default; the archived AWS backend when running inside AWS Lambda."""
    return aws if environ.get("AWS_LAMBDA_FUNCTION_NAME") else local


WAREHOUSE = os.getenv("WAREHOUSE", backend_default("duckdb", "redshift")).strip().lower()
WAREHOUSE_PATH = Path(os.getenv("WAREHOUSE_PATH", DATA_DIR / "warehouse.duckdb"))
RAW_DATA_DIR = Path(os.getenv("RAW_DATA_DIR", DATA_DIR / "raw"))

# Alert delivery channel (docs/local-stack-scope.md §6.4, R4). The local outbox is the default:
# each alert becomes a Markdown file under OUTBOX_DIR. SNS is the archived AWS channel, kept
# intact (R1), and stays the default inside Lambda so the archived image behaves as it always did.
ALERT_CHANNEL = os.getenv("ALERT_CHANNEL", backend_default("outbox", "sns")).strip().lower()
OUTBOX_DIR = Path(os.getenv("OUTBOX_DIR", PROJECT_ROOT / "outbox"))
# Who a pipeline alert is addressed to in the outbox. Named after the archived SNS topic.
ALERT_RECIPIENT = os.getenv("ALERT_RECIPIENT", "metric-pulse-alerts")
# CloudWatch pipeline metrics (archived AWS monitoring, monitoring/cloudwatch_metrics.py, kept intact).
# Off locally: with live AWS credentials still on the machine, a local run would otherwise really
# publish billed custom metrics. On inside Lambda, so the archived image behaves as it always did.
CLOUDWATCH_METRICS = os.getenv(
    "CLOUDWATCH_METRICS", backend_default("false", "true")).strip().lower() == "true"
