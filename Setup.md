# MetricPulse Setup Guide

## Prerequisites

- Python 3.10+
- AWS Account with billing enabled
- Git
- ~$5-10 for AWS resources during development

---

## Step 1: Clone Repository

```bash
git clone https://github.com/nkousik18/metric_pulse.git
cd metric_pulse
```

---

## Step 2: Python Environment

```bash
# Create virtual environment
python -m venv metric_venv

# Activate
source metric_venv/bin/activate  # macOS/Linux
# metric_venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Install Django dependencies
pip install django djangorestframework django-cors-headers
```

### requirements.txt
```
boto3>=1.28.0
redshift-connector>=2.0.0
pandas>=2.0.0
numpy>=1.24.0
scipy>=1.11.0
scikit-learn>=1.3.0
streamlit>=1.28.0
plotly>=5.18.0
jinja2>=3.1.0
python-dotenv>=1.0.0
pyyaml>=6.0.0
pytest>=7.4.0
dbt-redshift>=1.7.0
django>=4.2.0
djangorestframework>=3.14.0
django-cors-headers>=4.3.0
```

---

## Step 3: AWS Setup

### 3.1 Create IAM User

1. Go to **AWS Console** → **IAM** → **Users** → **Create user**
2. User name: `metric-pulse-dev`
3. Attach policies:
   - `AmazonS3FullAccess`
   - `AmazonRedshiftFullAccess`
   - `AmazonSNSFullAccess`
   - `AWSLambda_FullAccess`
   - `AmazonEC2ContainerRegistryFullAccess`
4. Create access keys (CLI access)
5. Save Access Key ID and Secret Access Key

### 3.2 Create S3 Bucket

```bash
aws s3 mb s3://metric-pulse-<your-name> --region us-east-1
```

Or via console:
1. Go to **S3** → **Create bucket**
2. Name: `metric-pulse-<your-name>`
3. Region: `us-east-1`

### 3.3 Create Redshift Serverless

1. Go to **Amazon Redshift** → **Serverless** → **Create workgroup**
2. Workgroup name: `metric-pulse-wg`
3. Base capacity: **8 RPU** (minimum)
4. Create namespace: `metric-pulse-ns`
5. Admin username: `admin`
6. Admin password: (save this)
7. Enable **Publicly accessible**
8. Create workgroup (~3 min)

### 3.4 Configure Security Group

1. In workgroup → **Network and security** tab
2. Click VPC security group
3. Edit inbound rules → Add rule:
   - Type: Custom TCP
   - Port: 5439
   - Source: My IP
4. Save

### 3.5 Create SNS Topic

```bash
aws sns create-topic --name metric-pulse-alerts --region us-east-1

# Subscribe your email
aws sns subscribe \
    --topic-arn arn:aws:sns:us-east-1:<ACCOUNT_ID>:metric-pulse-alerts \
    --protocol email \
    --notification-endpoint your@email.com \
    --region us-east-1
```

Check email and confirm subscription.

---

## Step 4: Environment Configuration

Create `.env` file in project root:

```bash
# AWS Credentials
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key_here
AWS_SECRET_ACCESS_KEY=your_secret_key_here

# S3
S3_BUCKET_NAME=metric-pulse-your-name

# Redshift
REDSHIFT_HOST=metric-pulse-wg.xxxx.us-east-2.redshift-serverless.amazonaws.com
REDSHIFT_PORT=5439
REDSHIFT_DATABASE=dev
REDSHIFT_USER=admin
REDSHIFT_PASSWORD=your_password_here

# SNS
SNS_TOPIC_ARN=arn:aws:sns:us-east-1:xxxx:metric-pulse-alerts

# Detection
ANOMALY_THRESHOLD_ZSCORE=2.0
LOOKBACK_DAYS=30

# Django
DJANGO_SECRET_KEY=your-secret-key-here
DJANGO_DEBUG=True
```

---

## Step 5: Download Dataset

1. Go to: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
2. Download and unzip to `data/raw/`
3. Verify files:
   ```
   data/raw/
   ├── olist_orders_dataset.csv
   ├── olist_order_items_dataset.csv
   ├── olist_customers_dataset.csv
   ├── olist_products_dataset.csv
   ├── olist_sellers_dataset.csv
   ├── olist_order_payments_dataset.csv
   └── product_category_name_translation.csv
   ```

---

## Step 6: Load Data

### 6.1 Upload to S3

```bash
python ingestion/upload_to_s3.py
```

### 6.2 Create Redshift Tables

```bash
python ingestion/setup_redshift_tables.py
```

### 6.3 Load Data to Redshift

```bash
python ingestion/s3_to_redshift.py
```

Expected output:
```
LOAD SUMMARY
==================================================
  raw_data.orders: 99,441 rows
  raw_data.order_items: 112,650 rows
  ...
Total rows loaded: 451,535
```

---

## Step 7: Configure dbt

### 7.1 Update dbt Profile

Edit `~/.dbt/profiles.yml`:

```yaml
dbt_project:
  outputs:
    dev:
      type: redshift
      host: metric-pulse-wg.xxxx.us-east-2.redshift-serverless.amazonaws.com
      port: 5439
      user: admin
      password: "your_password_here"
      dbname: dev
      schema: staging
      threads: 4
  target: dev
```

### 7.2 Test Connection

```bash
cd dbt_project
dbt debug
```

Expected: `All checks passed!`

### 7.3 Run Models

```bash
dbt run
```

### 7.4 Run Tests

```bash
dbt test
```

Expected: 37 tests pass.

---

## Step 8: Run the Application

### Option A: Django UI (Recommended)

```bash
cd /path/to/metric_pulse

# Run migrations (first time only)
python manage.py migrate

# Start Django server
python manage.py runserver
```

Open: **http://127.0.0.1:8000**

#### Django UI Features:
- **Date selectors** — Choose current and comparison dates
- **Metric dropdown** — Switch between Revenue, Orders, AOV
- **Anomaly threshold slider** — Adjust Z-score sensitivity
- **Interactive chart** — Click to select dates, toggle metrics
- **Drill-down panels** — Expand Geography, Product, Payment breakdowns
- **Copy/Download narrative** — Export analysis
- **Pipeline trigger** — Run analysis with one click

#### Django API Endpoints:
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health/` | GET | Health check |
| `/api/metrics/` | GET | Daily metrics data |
| `/api/anomalies/` | GET | Anomaly detection results |
| `/api/decomposition/` | GET | Segment contribution analysis |
| `/api/narrative/` | GET | Plain-English explanation |
| `/api/pipeline/` | POST | Trigger full pipeline |

Example API call:
```bash
curl http://127.0.0.1:8000/api/metrics/?days=30
```

### Option B: Streamlit Dashboard

```bash
streamlit run dashboard/app.py
```

Open: **http://localhost:8501**

### Option C: Command Line Pipeline

```bash
# Dry run (no alert sent)
python orchestration/run_pipeline.py --dry-run

# Full run with alert
python orchestration/run_pipeline.py --force-alert
```

---

## Step 9: Test Pipeline

### 9.1 Dry Run

```bash
python orchestration/run_pipeline.py --dry-run
```

Expected output:
```
============================================================
METRICPULSE PIPELINE SUMMARY
============================================================
Status: COMPLETED
Metric: total_revenue
Period: 2018-08-29 → 2018-09-03
Duration: 3.04s
Anomaly Detection:
  Days analyzed: 30
  Anomalies found: 0
Summary:
  Total Revenue decreased 90.6% on 2018-09-03. Primary driver: Credit Card (payment) contributed 106.6% of the change.
Alert Status: skipped
```

### 9.2 Full Run with Alert

```bash
python orchestration/run_pipeline.py --force-alert
```

Check your email for the alert.

---

## Quick Reference Commands

```bash
# Activate environment
source metric_venv/bin/activate

# Run Django UI
python manage.py runserver

# Run Streamlit dashboard
streamlit run dashboard/app.py

# Run dbt models
cd dbt_project && dbt run

# Run dbt tests
cd dbt_project && dbt test

# Run pipeline (dry)
python orchestration/run_pipeline.py --dry-run

# Run pipeline (with alert)
python orchestration/run_pipeline.py --force-alert

# Run unit tests
pytest tests/ -v
```

---

## Project Structure

```
metric_pulse/
├── config/
│   ├── logging_config.py
│   └── settings.py
├── ingestion/
│   ├── upload_to_s3.py
│   ├── s3_to_redshift.py
│   └── setup_redshift_tables.py
├── dbt_project/
│   ├── models/staging/
│   ├── models/marts/
│   └── models/metrics/
├── detection/
│   └── anomaly_detector.py
├── decomposition/
│   └── decomposer.py
├── narrative/
│   └── generator.py
├── alerting/
│   └── sns_publisher.py
├── orchestration/
│   └── run_pipeline.py
├── monitoring/
│   └── cloudwatch_metrics.py
├── dashboard_api/          # Django REST API
│   ├── views.py
│   └── urls.py
├── metric_pulse_web/       # Django settings
│   ├── settings.py
│   └── urls.py
├── templates/
│   └── index.html          # Django UI
├── dashboard/
│   └── app.py              # Streamlit UI
├── deploy/
│   ├── deploy_lambda.sh
│   └── setup_lambda.sh
├── tests/
├── .github/workflows/
│   ├── ci.yml
│   └── cd.yml
├── Dockerfile
├── lambda_handler.py
├── manage.py               # Django entry point
├── .env
└── requirements.txt
```

---

## Troubleshooting

### Django won't start
```bash
# Check if port 8000 is in use
lsof -i :8000

# Kill process if needed
kill -9 <PID>

# Or use different port
python manage.py runserver 8080
```

### Connection Timeout to Redshift
- Check security group allows your IP on port 5439
- Verify "Publicly accessible" is enabled
- Confirm your IP hasn't changed

### dbt Connection Failed
- Verify password in `~/.dbt/profiles.yml`
- Check host doesn't include `https://` or port

### SNS Email Not Received
- Confirm subscription via email link
- Check spam folder
- Verify SNS_TOPIC_ARN in .env

### API returns empty data
- Check Redshift connection in .env
- Verify dbt models have run: `cd dbt_project && dbt run`

---

## Cost Management

### Estimated Costs (Development)

| Service | Usage | Cost |
|---------|-------|------|
| Redshift Serverless | ~2-4 hrs/day | $1-4/day |
| S3 | 50MB storage | $0.02/month |
| SNS | <100 emails | Free |
| Lambda | <1M requests | Free tier |

### Cost Saving Tips

1. **Pause Redshift** when not using (auto-pauses after idle)
2. **Set billing alert** at $10/month
3. **Delete resources** when project complete

---

## Next Steps

1. **Run the Django UI** and explore all features
2. **Customize thresholds** — Adjust Z-score in `.env` or UI
3. **Deploy to Lambda** — Complete serverless deployment
4. **Add Slack integration** — Webhook-based alerts
5. **Schedule runs** — Set up EventBridge for daily execution