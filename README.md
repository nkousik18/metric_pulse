# MetricPulse

**Automated Root Cause Analysis Engine**

When business metrics move unexpectedly, MetricPulse automatically identifies what drove the change — before anyone asks.

🔗 **Live Demo:** [metricpulse-h9lu.onrender.com](https://metricpulse-h9lu.onrender.com)

---

## The Problem

Every analyst has heard: *"Revenue dropped 15% yesterday — why?"*

The typical answer takes **2-4 hours**:
- Pull data from multiple systems
- Slice by region, product, channel
- Build spreadsheets manually
- Write email explaining findings

## The Solution

MetricPulse automates the entire workflow in **under 30 seconds**:
- **Detect** — Statistical anomaly detection using Z-score analysis
- **Decompose** — Break down changes across geography, product, and payment dimensions
- **Explain** — Generate plain-English narrative automatically
- **Alert** — Proactive email via AWS SNS before anyone asks

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA INGESTION                              │
│  Kaggle Dataset → S3 (raw/) → Redshift (raw_data schema)           │
│  451K rows, 7 tables                                                │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      dbt TRANSFORMATION                             │
│  staging/           marts/               metrics/                   │
│  • stg_orders       • fact_daily_metrics • metric_by_geography     │
│  • stg_order_items  • dim_geography      • metric_by_product       │
│  • stg_customers    • dim_product        • metric_by_payment       │
│  • stg_products     • dim_payment                                  │
│                                                                     │
│  11 models │ 37 automated tests │ 100% pass rate                   │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     DETECTION & ANALYSIS                            │
│  Anomaly Detector ──→ Decomposer ──→ Narrative Generator           │
│  (Z-score)            (3 dimensions)   (Jinja2 templates)          │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        DELIVERY LAYER                               │
│       SNS Email Alerts  │  Django REST API  │  Dashboard UI        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Data Storage** | AWS S3, AWS Redshift Serverless |
| **Transformation** | dbt (11 models, 37 tests) |
| **Backend** | Python, Django REST Framework |
| **Detection** | NumPy, SciPy (Z-score analysis) |
| **Alerting** | AWS SNS |
| **Frontend** | Tailwind CSS, Chart.js |
| **Containerization** | Docker |
| **CI/CD** | GitHub Actions |
| **Hosting** | Render |

---

## Project Structure

```
metric_pulse/
├── config/                  # Configuration and settings
│   ├── settings.py
│   └── logging_config.py
├── ingestion/               # Data ingestion scripts
│   ├── upload_to_s3.py
│   ├── s3_to_redshift.py
│   └── setup_redshift_tables.py
├── detection/               # Anomaly detection
│   └── anomaly_detector.py
├── decomposition/           # Metric decomposition
│   └── decomposer.py
├── narrative/               # Narrative generation
│   ├── generator.py
│   └── templates/
├── alerting/                # SNS alerting
│   └── sns_publisher.py
├── orchestration/           # Pipeline orchestration
│   └── run_pipeline.py
├── monitoring/              # CloudWatch metrics
│   └── cloudwatch_metrics.py
├── dashboard_api/           # Django REST API
│   ├── views.py
│   └── urls.py
├── metric_pulse_web/        # Django project settings
├── templates/               # Frontend templates
│   ├── base.html
│   ├── index.html
│   └── partials/
├── dbt_project/             # dbt models and tests
│   ├── models/
│   └── tests/
├── tests/                   # Unit tests
├── .github/workflows/       # CI/CD pipelines
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Quick Start

### Prerequisites

- Python 3.12+
- AWS Account (S3, Redshift, SNS)
- dbt CLI

### 1. Clone the Repository

```bash
git clone https://github.com/nkousik18/metric_pulse.git
cd metric_pulse
```

### 2. Create Virtual Environment

```bash
python -m venv metric_venv
source metric_venv/bin/activate  # On Windows: metric_venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the project root:

```env
# AWS Credentials
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-1

# S3
S3_BUCKET_NAME=your-bucket-name

# Redshift
REDSHIFT_HOST=your-workgroup.region.redshift-serverless.amazonaws.com
REDSHIFT_PORT=5439
REDSHIFT_DATABASE=dev
REDSHIFT_USER=admin
REDSHIFT_PASSWORD=your_password

# SNS
SNS_TOPIC_ARN=arn:aws:sns:region:account:topic-name

# Django
DJANGO_SECRET_KEY=your_secret_key
DJANGO_DEBUG=True

# Pipeline
ANOMALY_THRESHOLD_ZSCORE=2.0
LOOKBACK_DAYS=30
```

### 4. Set Up AWS Infrastructure

```bash
# Upload raw data to S3
python -m ingestion.upload_to_s3

# Create Redshift tables and load data
python -m ingestion.setup_redshift_tables
python -m ingestion.s3_to_redshift
```

### 5. Run dbt Transformations

```bash
cd dbt_project
dbt deps
dbt run
dbt test
```

### 6. Run the Application

```bash
# Run Django server
python manage.py migrate
python manage.py runserver

# Access at http://127.0.0.1:8000
```

### 7. Run the Pipeline

```bash
# Dry run (no alerts)
python -m orchestration.run_pipeline --dry-run

# Full run with alerts
python -m orchestration.run_pipeline --force-alert
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health/` | GET | Health check |
| `/api/metrics/` | GET | Fetch daily metrics |
| `/api/anomalies/` | GET | Detect anomalies |
| `/api/decomposition/` | GET | Decompose metric changes |
| `/api/narrative/` | GET | Generate root cause narrative |
| `/api/pipeline/` | POST | Trigger pipeline run |
| `/api/contact/` | POST | Submit contact form |

---

## Key Metrics

| Metric | Value |
|--------|-------|
| Data Volume | 451K rows |
| Automated Tests | 37 |
| Pipeline Speed | < 5 seconds |
| Time Saved | 99.6% (2 hrs → 30 sec) |
| API Endpoints | 7 |
| dbt Models | 11 |

---

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html
```

---

## Deployment

### Deploy to Render

1. Connect GitHub repository to Render
2. Configure environment variables
3. Deploy automatically on push to `main`

### Docker

```bash
# Build image
docker build -t metricpulse .

# Run container
docker run -p 8000:8000 --env-file .env metricpulse
```

---

## Future Enhancements

- [ ] AWS Lambda serverless deployment
- [ ] Additional decomposition dimensions
- [ ] Slack integration for alerts
- [ ] Scheduled pipeline runs with Airflow
- [ ] ML-based anomaly detection

---

## Author

**Kousik Nandury**

-  MS Data Analytics Engineering, Northeastern University
-  2 years experience at Capgemini
-  [LinkedIn](https://www.linkedin.com/in/kousik-nandury)
-  [GitHub](https://github.com/nkousik18)
-  nandury.k@northeastern.edu

---

## License

This project is for portfolio and educational purposes.