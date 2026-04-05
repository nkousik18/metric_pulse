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
```

---

## Step 3: AWS Setup

### 3.1 Create IAM User

1. Go to **AWS Console** → **IAM** → **Users** → **Create user**
2. User name: `metric-pulse-dev`
3. Attach policies:
   - `AmazonS3FullAccess`
   - `AmazonRedshiftFullAccess`
   - `AmazonSageMakerFullAccess`
   - `AmazonSNSFullAccess`
4. Create access keys (CLI access)
5. Save Access Key ID and Secret Access Key

### 3.2 Create S3 Bucket

```bash
# After configuring .env (see Step 4)
python ingestion/upload_to_s3.py
```

Or manually:
1. Go to **S3** → **Create bucket**
2. Name: `metric-pulse-<your-name>`
3. Region: `us-east-1`
4. Keep defaults

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
python alerting/sns_publisher.py --setup --email your@email.com
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
REDSHIFT_HOST=metric-pulse-wg.xxxx.us-east-1.redshift-serverless.amazonaws.com
REDSHIFT_PORT=5439
REDSHIFT_DATABASE=dev
REDSHIFT_USER=admin
REDSHIFT_PASSWORD=your_password_here

# SNS
SNS_TOPIC_ARN=arn:aws:sns:us-east-1:xxxx:metric-pulse-alerts

# Detection
ANOMALY_THRESHOLD_ZSCORE=2.0
LOOKBACK_DAYS=30
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

Expected output:
```
UPLOAD SUMMARY
==================================================
Successful: 7
  ✓ olist_orders_dataset.csv
  ✓ olist_order_items_dataset.csv
  ...
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
      host: metric-pulse-wg.xxxx.us-east-1.redshift-serverless.amazonaws.com
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

Expected: All models succeed.

### 7.4 Run Tests

```bash
dbt test
```

---

## Step 8: Test Pipeline

### 8.1 Dry Run

```bash
cd /path/to/metric_pulse
python orchestration/run_pipeline.py --dry-run
```

### 8.2 Full Run with Alert

```bash
python orchestration/run_pipeline.py --force-alert
```

Check your email for the alert.

---

## Step 9: Launch Dashboard

```bash
streamlit run dashboard/app.py
```

Opens at: http://localhost:8501

---

## Quick Reference Commands

```bash
# Activate environment
source metric_venv/bin/activate

# Run dbt models
cd dbt_project && dbt run

# Run dbt tests
cd dbt_project && dbt test

# Run pipeline (dry)
python orchestration/run_pipeline.py --dry-run

# Run pipeline (with alert)
python orchestration/run_pipeline.py --force-alert

# Launch dashboard
streamlit run dashboard/app.py

# Test individual components
python detection/anomaly_detector.py
python decomposition/decomposer.py
python narrative/generator.py
```

---

## Troubleshooting

### Connection Timeout to Redshift
- Check security group allows your IP on port 5439
- Verify "Publicly accessible" is enabled

### dbt Connection Failed
- Verify password in `~/.dbt/profiles.yml`
- Check host doesn't include `https://` or port

### SNS Email Not Received
- Confirm subscription via email link
- Check spam folder
- Verify SNS_TOPIC_ARN in .env

### S3 Upload Fails
- Verify AWS credentials in .env
- Check bucket name is unique globally

---

## Cost Management

### Estimated Costs (Development)

| Service | Usage | Cost |
|---------|-------|------|
| Redshift Serverless | ~2-4 hrs/day | $1-4/day |
| S3 | 50MB storage | $0.02/month |
| SNS | <100 emails | Free |

### Cost Saving Tips

1. **Pause Redshift** when not using (auto-pauses after idle)
2. **Set billing alert** at $10/month
3. **Delete resources** when project complete:
   ```bash
   # Delete S3 bucket
   aws s3 rb s3://metric-pulse-your-name --force
   
   # Delete Redshift workgroup (via console)
   # Delete SNS topic (via console)
   ```

---

## Project Structure

```
metric_pulse/
├── config/
│   ├── logging_config.py    # Centralized logging
│   └── settings.py          # Environment variables
├── ingestion/
│   ├── upload_to_s3.py      # S3 upload
│   ├── s3_to_redshift.py    # Redshift loading
│   └── setup_redshift_tables.py
├── dbt_project/
│   ├── models/
│   │   ├── staging/         # Cleaned views
│   │   ├── marts/           # Fact & dimension tables
│   │   └── metrics/         # Decomposition tables
│   └── tests/               # Data quality tests
├── detection/
│   └── anomaly_detector.py  # Z-score detection
├── decomposition/
│   └── decomposer.py        # Segment analysis
├── narrative/
│   └── generator.py         # Text generation
├── alerting/
│   └── sns_publisher.py     # Email alerts
├── orchestration/
│   └── run_pipeline.py      # Main pipeline
├── dashboard/
│   └── app.py               # Streamlit UI
├── .env                     # Configuration (git-ignored)
├── requirements.txt
└── README.md
```

---

## Next Steps After Setup

1. **Customize thresholds**: Adjust `ANOMALY_THRESHOLD_ZSCORE` in .env
2. **Add metrics**: Extend to order_count, avg_order_value
3. **Schedule runs**: Set up cron or Airflow
4. **Add Slack**: Integrate Slack webhook for alerts
5. **Deploy**: Consider AWS Lambda or ECS for production