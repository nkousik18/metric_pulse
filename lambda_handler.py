"""
AWS Lambda handler for MetricPulse pipeline.
"""

import os
import json
import logging
from datetime import datetime

# Set up logging for Lambda
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Import pipeline components
from orchestration.run_pipeline import run_pipeline

def handler(event, context):
    """
    Lambda entry point.
    
    Triggered by:
    - EventBridge scheduled rule (daily)
    - Manual invocation
    - API Gateway (optional)
    
    Args:
        event: Lambda event payload
        context: Lambda context object
    
    Returns:
        Response dict with status and results
    """
    logger.info(f"MetricPulse Lambda triggered at {datetime.now().isoformat()}")
    logger.info(f"Event: {json.dumps(event)}")
    
    # Extract parameters from event
    metric = event.get('metric', 'total_revenue')
    threshold = event.get('threshold', None)
    force_alert = event.get('force_alert', False)
    dry_run = event.get('dry_run', False)
    
    try:
        # Run pipeline
        results = run_pipeline(
            metric=metric,
            threshold=threshold,
            force_alert=force_alert,
            dry_run=dry_run
        )
        
        logger.info(f"Pipeline completed: {results['status']}")
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': results['status'],
                'metric': results['metric'],
                'anomaly_count': results.get('detection', {}).get('anomaly_count', 0),
                'alert_status': results.get('alert', {}).get('status', 'unknown'),
                'summary': results.get('narratives', {}).get('summary', ''),
                'executed_at': datetime.now().isoformat()
            })
        }
        
    except Exception as e:
        logger.error(f"Pipeline failed: {str(e)}")
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'status': 'error',
                'error': str(e),
                'executed_at': datetime.now().isoformat()
            })
        }


# For local testing
if __name__ == "__main__":
    test_event = {
        'metric': 'total_revenue',
        'force_alert': False,
        'dry_run': True
    }
    
    result = handler(test_event, None)
    print(json.dumps(json.loads(result['body']), indent=2))
