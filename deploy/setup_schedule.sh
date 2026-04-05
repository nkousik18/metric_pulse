#!/bin/bash
set -e

AWS_REGION="${AWS_REGION:-us-east-1}"
LAMBDA_FUNCTION_NAME="metric-pulse-pipeline"
RULE_NAME="metric-pulse-daily"

echo "Setting up daily schedule..."

# Create EventBridge rule (runs daily at 8 AM UTC)
aws events put-rule \
    --name $RULE_NAME \
    --schedule-expression "cron(0 8 * * ? *)" \
    --state ENABLED \
    --region $AWS_REGION

# Get Lambda ARN
LAMBDA_ARN=$(aws lambda get-function --function-name $LAMBDA_FUNCTION_NAME --query 'Configuration.FunctionArn' --output text --region $AWS_REGION)

# Add permission for EventBridge to invoke Lambda
aws lambda add-permission \
    --function-name $LAMBDA_FUNCTION_NAME \
    --statement-id "EventBridgeInvoke" \
    --action "lambda:InvokeFunction" \
    --principal events.amazonaws.com \
    --source-arn arn:aws:events:$AWS_REGION:$(aws sts get-caller-identity --query Account --output text):rule/$RULE_NAME \
    --region $AWS_REGION 2>/dev/null || echo "Permission already exists"

# Add target
aws events put-targets \
    --rule $RULE_NAME \
    --targets "Id"="1","Arn"="$LAMBDA_ARN","Input"="{\"metric\":\"total_revenue\",\"force_alert\":false}" \
    --region $AWS_REGION

echo ""
echo "Schedule created: Daily at 8:00 AM UTC"
echo "Rule: $RULE_NAME"
