#!/bin/bash
set -e

# Configuration
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO_NAME="metric-pulse"
LAMBDA_FUNCTION_NAME="metric-pulse-pipeline"
IMAGE_TAG="latest"

echo "================================================"
echo "MetricPulse Lambda Deployment"
echo "================================================"
echo "Region: $AWS_REGION"
echo "Account: $AWS_ACCOUNT_ID"
echo ""

# Step 1: Create ECR repository (if not exists)
echo "Step 1: Creating ECR repository..."
aws ecr describe-repositories --repository-names $ECR_REPO_NAME --region $AWS_REGION 2>/dev/null || \
    aws ecr create-repository --repository-name $ECR_REPO_NAME --region $AWS_REGION

# Step 2: Login to ECR
echo "Step 2: Logging into ECR..."
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

# Step 3: Build Docker image
echo "Step 3: Building Docker image..."
docker build -t $ECR_REPO_NAME:$IMAGE_TAG .

# Step 4: Tag and push to ECR
echo "Step 4: Pushing to ECR..."
docker tag $ECR_REPO_NAME:$IMAGE_TAG $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME:$IMAGE_TAG
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME:$IMAGE_TAG

# Step 5: Update Lambda function
echo "Step 5: Updating Lambda function..."
aws lambda update-function-code \
    --function-name $LAMBDA_FUNCTION_NAME \
    --image-uri $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO_NAME:$IMAGE_TAG \
    --region $AWS_REGION 2>/dev/null || \
echo "Lambda function doesn't exist yet. Create it with setup_lambda.sh first."

echo ""
echo "================================================"
echo "Deployment complete!"
echo "================================================"
