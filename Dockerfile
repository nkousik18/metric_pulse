FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install only production dependencies
COPY requirements-lambda.txt .
RUN pip install --no-cache-dir -r requirements-lambda.txt

# Copy only necessary code
COPY config/ ./config/
COPY detection/ ./detection/
COPY decomposition/ ./decomposition/
COPY narrative/ ./narrative/
COPY alerting/ ./alerting/
COPY orchestration/ ./orchestration/
COPY lambda_handler.py .

# Lambda adapter
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.8.4 /lambda-adapter /opt/extensions/lambda-adapter

ENV PORT=8080
CMD ["python", "lambda_handler.py"]
