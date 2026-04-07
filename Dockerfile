FROM public.ecr.aws/lambda/python:3.12

# Copy requirements and install
COPY requirements-lambda.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements-lambda.txt

# Copy application code
COPY config/ ${LAMBDA_TASK_ROOT}/config/
COPY detection/ ${LAMBDA_TASK_ROOT}/detection/
COPY decomposition/ ${LAMBDA_TASK_ROOT}/decomposition/
COPY narrative/ ${LAMBDA_TASK_ROOT}/narrative/
COPY alerting/ ${LAMBDA_TASK_ROOT}/alerting/
COPY orchestration/ ${LAMBDA_TASK_ROOT}/orchestration/
COPY lambda_handler.py ${LAMBDA_TASK_ROOT}/

CMD ["lambda_handler.handler"]
