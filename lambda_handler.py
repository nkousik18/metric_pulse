"""
AWS Lambda handler for MetricPulse pipeline.
"""

import os
import json
import logging
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    """Lambda entry point."""
    logger.info(f"MetricPulse Lambda triggered at {datetime.now().isoformat()}")
    logger.info(f"Event: {json.dumps(event)}")
    
    # Import here to avoid cold start issues
    from orchestration.run_pipeline import run_pipeline
    
    metric = event.get('metric', 'total_revenue')
    force_alert = event.get('force_alert', False)
    dry_run = event.get('dry_run', False)
    
    try:
        results = run_pipeline(
            metric=metric,
            force_alert=force_alert,
            dry_run=dry_run,
            publish_metrics=False
        )
        
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
            'body': json.dumps({'status': 'error', 'error': str(e)})
        }
