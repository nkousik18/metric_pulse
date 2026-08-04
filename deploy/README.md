# deploy/

Three standalone Bash scripts for provisioning and deploying the analytics pipeline (not the Django app) as a Docker-based AWS Lambda function, triggered on a daily schedule via EventBridge. **None of these scripts are invoked by CI/CD.** `.github/workflows/cd.yml` doesn't deploy anything itself — its steps are checkout → Python setup → install deps → configure AWS credentials → an `echo` placeholder where `dbt run` would go → a final "Deployment completed successfully" echo. There is no Render deploy step in this workflow at all; Render deploys separately via its own git-push auto-deploy hook, entirely outside GitHub Actions. Lambda deployment (this folder's scripts) is entirely manual. All three scripts use `set -e` (exit on first error) and assume the AWS CLI is installed and already authenticated (`aws sts get-caller-identity` must succeed).

## Files

| File | Purpose | Run order |
|------|---------|-----------|
| `setup_lambda.sh` | One-time: create IAM role + Lambda function | 1st (once) |
| `deploy_lambda.sh` | Build image, push to ECR, update Lambda code | 2nd, and every subsequent redeploy |
| `setup_schedule.sh` | One-time: create the daily EventBridge trigger | 3rd (once) |

## `setup_lambda.sh` — first-time IAM + Lambda creation

1. Reads `AWS_REGION` (default `us-east-1`) and resolves `AWS_ACCOUNT_ID` via `aws sts get-caller-identity`.
2. Writes a Lambda trust policy to `/tmp/trust-policy.json` (allows `lambda.amazonaws.com` to assume the role).
3. `aws iam create-role --role-name metric-pulse-lambda-role ...` — if the role already exists, the command's stderr is suppressed and a "Role already exists" message is printed instead (non-fatal, script continues).
4. Attaches 4 managed policies to that role: `AWSLambdaBasicExecutionRole`, `AmazonS3ReadOnlyAccess`, `AmazonSNSFullAccess`, `AmazonRedshiftDataFullAccess`.
5. `sleep 10` to let IAM role propagation settle before Lambda creation.
6. `aws lambda create-function --function-name metric-pulse-pipeline --package-type Image ...` pointing at `<account>.dkr.ecr.<region>.amazonaws.com/metric-pulse:latest` — **this will fail if the image doesn't exist in ECR yet**, since `deploy_lambda.sh` (which creates the ECR repo and pushes the image) hasn't necessarily run first. In practice you need the ECR repo + at least one pushed image before this step succeeds; the script does not create the ECR repo itself. Timeout 300s, memory 512MB.
7. Prints next-steps reminder (set Lambda env vars in console, run `deploy_lambda.sh`, set up the schedule).

## `deploy_lambda.sh` — build & push image, update Lambda

1. Resolves `AWS_REGION`/`AWS_ACCOUNT_ID` the same way.
2. `aws ecr describe-repositories --repository-names metric-pulse` — creates the ECR repo via `aws ecr create-repository` only if `describe-repositories` fails (repo doesn't exist yet). **This is the step that actually creates the ECR repo referenced by `setup_lambda.sh` step 6** — meaning in practice `deploy_lambda.sh` needs to run (or at least this ECR-create step) before `setup_lambda.sh`'s `create-function` call can succeed, despite the numbered filenames suggesting the opposite order.
3. `aws ecr get-login-password | docker login` — authenticates Docker to ECR.
4. `docker build -t metric-pulse:latest .` — builds from the repo-root `Dockerfile` (the Lambda-specific image containing `config/`, `detection/`, `decomposition/`, `narrative/`, `alerting/`, `orchestration/`, `lambda_handler.py` — see root `Dockerfile`).
5. `docker tag` + `docker push` to `<account>.dkr.ecr.<region>.amazonaws.com/metric-pulse:latest`.
6. `aws lambda update-function-code --function-name metric-pulse-pipeline --image-uri ...` — if this fails (function doesn't exist yet), prints "Lambda function doesn't exist yet. Create it with setup_lambda.sh first." and continues rather than exiting (the `set -e` doesn't trigger because the failure is piped into `|| echo ...`).

**Practical run order the first time:** run `deploy_lambda.sh` first (creates ECR repo + pushes an image, and harmlessly no-ops on the `update-function-code` step since the function doesn't exist yet), *then* `setup_lambda.sh` (now the image it references in `create-function` exists), then `deploy_lambda.sh` again for any subsequent code change.

## `setup_schedule.sh` — daily EventBridge trigger

1. `aws events put-rule --name metric-pulse-daily --schedule-expression "cron(0 8 * * ? *)"` — runs daily at 8:00 AM UTC.
2. Looks up the Lambda's ARN via `aws lambda get-function`.
3. `aws lambda add-permission` — grants EventBridge permission to invoke the function (non-fatal if it already exists).
4. `aws events put-targets` — wires the rule to the Lambda, passing a fixed JSON payload as input: `{"metric": "total_revenue", "force_alert": false}`. This is a static payload — the metric/force_alert values are baked into the rule at setup time, not configurable per-invocation without re-running this script.

## Running

```bash
export AWS_REGION=us-east-1   # optional, defaults to us-east-1
chmod +x deploy/*.sh          # already executable in this repo (rwxr-xr-x)

./deploy/deploy_lambda.sh     # build + push image (creates ECR repo first time)
./deploy/setup_lambda.sh      # create IAM role + Lambda function (first time only)
./deploy/deploy_lambda.sh     # redeploy after any code change
./deploy/setup_schedule.sh    # create the daily 8am UTC trigger (first time only)
```

## Env vars

| Var | Default | Used by |
|-----|---------|---------|
| `AWS_REGION` | `us-east-1` | All 3 scripts |

AWS credentials themselves come from the ambient AWS CLI configuration (`~/.aws/credentials`, or an assumed role) — none of these scripts read `.env` or `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` directly; they rely on `aws` CLI auth already being set up in the shell.

## Gotchas

- No `-region` propagation into the Lambda's own runtime env vars — the deployed function still needs its full `.env`-equivalent (`REDSHIFT_HOST`, `SNS_TOPIC_ARN`, etc.) set manually in the Lambda console, per `setup_lambda.sh`'s own "next steps" output. None of these scripts set Lambda environment variables.
- `setup_schedule.sh`'s payload hardcodes `total_revenue` / `force_alert: false` — to schedule a different metric or force alerts on the daily run, this script must be edited and rerun (it will just update the existing rule/target, it's idempotent for that purpose).
- All three scripts assume the working directory contains a `Dockerfile` at the repo root when `deploy_lambda.sh` runs `docker build -t metric-pulse:latest .` — must be run from the repo root, not from inside `deploy/`.
