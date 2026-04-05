"""
CloudWatch metrics for pipeline monitoring.
"""

import os
import boto3
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


def get_cloudwatch_client():
    """Create CloudWatch client."""
    return boto3.client(
        'cloudwatch',
        region_name=os.getenv('AWS_REGION', 'us-east-1'),
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
    )


def publish_metric(metric_name: str, value: float, unit: str = 'Count'):
    """
    Publish custom metric to CloudWatch.
    
    Args:
        metric_name: Name of the metric
        value: Metric value
        unit: Unit type (Count, Seconds, etc.)
    """
    client = get_cloudwatch_client()
    
    client.put_metric_data(
        Namespace='MetricPulse',
        MetricData=[
            {
                'MetricName': metric_name,
                'Value': value,
                'Unit': unit,
                'Timestamp': datetime.utcnow()
            }
        ]
    )


def publish_pipeline_metrics(results: dict):
    """
    Publish pipeline execution metrics.
    
    Args:
        results: Pipeline results dictionary
    """
    # Execution status (1 = success, 0 = failure)
    status = 1 if results.get('status') == 'completed' else 0
    publish_metric('PipelineExecutionSuccess', status)
    
    # Anomaly count
    anomaly_count = results.get('detection', {}).get('anomaly_count', 0)
    publish_metric('AnomaliesDetected', anomaly_count)
    
    # Alert sent
    alert_sent = 1 if results.get('alert', {}).get('status') == 'sent' else 0
    publish_metric('AlertsSent', alert_sent)


def create_dashboard():
    """Create CloudWatch dashboard for MetricPulse."""
    client = get_cloudwatch_client()
    
    dashboard_body = {
        "widgets": [
            {
                "type": "metric",
                "x": 0, "y": 0,
                "width": 8, "height": 6,
                "properties": {
                    "title": "Pipeline Executions",
                    "metrics": [
                        ["MetricPulse", "PipelineExecutionSuccess", {"stat": "Sum", "period": 86400}]
                    ],
                    "region": os.getenv('AWS_REGION', 'us-east-1')
                }
            },
            {
                "type": "metric",
                "x": 8, "y": 0,
                "width": 8, "height": 6,
                "properties": {
                    "title": "Anomalies Detected",
                    "metrics": [
                        ["MetricPulse", "AnomaliesDetected", {"stat": "Sum", "period": 86400}]
                    ],
                    "region": os.getenv('AWS_REGION', 'us-east-1')
                }
            },
            {
                "type": "metric",
                "x": 16, "y": 0,
                "width": 8, "height": 6,
                "properties": {
                    "title": "Alerts Sent",
                    "metrics": [
                        ["MetricPulse", "AlertsSent", {"stat": "Sum", "period": 86400}]
                    ],
                    "region": os.getenv('AWS_REGION', 'us-east-1')
                }
            }
        ]
    }
    
    import json
    client.put_dashboard(
        DashboardName='MetricPulse',
        DashboardBody=json.dumps(dashboard_body)
    )
    
    print("Dashboard created: MetricPulse")


if __name__ == "__main__":
    create_dashboard()
    print("CloudWatch dashboard created successfully")
