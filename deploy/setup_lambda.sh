#!/bin/bash
set -e

# Configuration
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO_NAME="metric-pulse"
LAMBDA_FUNCTION_NAME="metric-pulse-pipeline"
LAMBDA_ROLE_NAME="metric-pulse-lambda-role"

echo "================================================"
echo "MetricPulse Lambda Setup (First Time)"
echo "================================================"

# Step 1: Create IAM Role for Lambda
echo "Step 1: Creating IAM role..."

cat > /tmp/trust-policy.json << 'TRUST'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
TRUST

aws iam create-role \
    --role-name $LAMBDA_ROLE_NAME \
    --assume-role-policy-document file:///tmp/trust-policy.json \
    --region $AWS_REGION 2>/dev/null || echo "Role already exists"

# Attach policies
aws iam attach-role-policy --role-name $LAMBDA_ROLE_NAME \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam attach-role-policy --role-name $LAMBDA_ROLE_NAME \
    --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess
aws iam attach-role-policy --role-name $LAMBDA_ROLE_NAME \
    --policy-arn arn:aws:iam::aws:policy/AmazonSNSFullAccess
aws iam attach-role-policy --role-name $LAMBDA_ROLE_NAME \
    --policy-arn arn:aws:iam::aws:policy/AmazonRedshiftDataFullAccess

echo "Waiting for role to propagate..."
sleep 10

# Step 2: Create Lambda function
echo "Step 2: Creating Lambda function..."

aws lambda create-function \
    --function-name $LAMBDA_FUNCTION_NAME \
    --package-type Image \
    --code ImageUri=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME:latest \
    --role arn:aws:iam::$AWS_ACCOUNT_ID:role/$LAMBDA_ROLE_NAME \
    --timeout 300 \
    --memory-size 512 \
    --region $AWS_REGION

echo ""
echo "================================================"
echo "Lambda setup complete!"
echo "================================================"
echo ""
echo "Next steps:"
echo "1. Set environment variables in Lambda console"
echo "2. Run: ./deploy/deploy_lambda.sh"
echo "3. Set up EventBridge schedule"
