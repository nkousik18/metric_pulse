"""
Publish alerts to AWS SNS.
"""

import os
import sys
from pathlib import Path
from typing import Dict, Optional

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.logging_config import setup_logger

load_dotenv()

logger = setup_logger(__name__)


def get_sns_client():
    """Create SNS client."""
    try:
        client = boto3.client(
            'sns',
            region_name=os.getenv('AWS_REGION'),
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        return client
    except Exception as e:
        logger.error(f"Failed to create SNS client: {e}")
        raise


def create_topic_if_not_exists(topic_name: str = 'metric-pulse-alerts') -> str:
    """
    Create SNS topic if it doesn't exist.
    
    Returns:
        Topic ARN
    """
    client = get_sns_client()
    
    try:
        response = client.create_topic(Name=topic_name)
        topic_arn = response['TopicArn']
        logger.info(f"SNS topic ready: {topic_arn}")
        return topic_arn
    except ClientError as e:
        logger.error(f"Failed to create topic: {e}")
        raise


def subscribe_email(topic_arn: str, email: str) -> str:
    """
    Subscribe email to SNS topic.
    
    Returns:
        Subscription ARN
    """
    client = get_sns_client()
    
    try:
        response = client.subscribe(
            TopicArn=topic_arn,
            Protocol='email',
            Endpoint=email
        )
        subscription_arn = response['SubscriptionArn']
        logger.info(f"Subscription created: {email} (confirm via email)")
        return subscription_arn
    except ClientError as e:
        logger.error(f"Failed to subscribe: {e}")
        raise


def publish_alert(
    subject: str,
    message: str,
    topic_arn: Optional[str] = None
) -> Dict:
    """
    Publish alert to SNS topic.
    
    Args:
        subject: Email subject line
        message: Alert message body
        topic_arn: SNS topic ARN (uses env var if not provided)
    
    Returns:
        SNS publish response
    """
    if topic_arn is None:
        topic_arn = os.getenv('SNS_TOPIC_ARN')
    
    if not topic_arn:
        logger.warning("No SNS_TOPIC_ARN configured, skipping alert")
        return {'status': 'skipped', 'reason': 'no_topic_arn'}
    
    client = get_sns_client()
    
    try:
        response = client.publish(
            TopicArn=topic_arn,
            Subject=subject[:100],  # SNS subject limit
            Message=message
        )
        
        message_id = response['MessageId']
        logger.info(f"Alert published: {message_id}")
        
        return {
            'status': 'sent',
            'message_id': message_id,
            'topic_arn': topic_arn
        }
        
    except ClientError as e:
        logger.error(f"Failed to publish alert: {e}")
        return {'status': 'error', 'error': str(e)}


def publish_metric_alert(narratives: Dict, topic_arn: Optional[str] = None) -> Dict:
    """
    Publish metric alert using generated narratives.
    
    Args:
        narratives: Output from narrative generator
        topic_arn: Optional topic ARN override
    
    Returns:
        Publish result
    """
    subject = narratives.get('email_subject', 'MetricPulse Alert')
    message = narratives.get('full', narratives.get('summary', 'No details available'))
    
    # Clean up markdown for email
    message = message.replace('**', '').replace('*', '')
    
    return publish_alert(subject, message, topic_arn)


def setup_sns(email: Optional[str] = None) -> Dict:
    """
    Set up SNS topic and optionally subscribe email.
    
    Args:
        email: Email to subscribe (optional)
    
    Returns:
        Setup results
    """
    logger.info("Setting up SNS")
    
    results = {}
    
    # Create topic
    topic_arn = create_topic_if_not_exists()
    results['topic_arn'] = topic_arn
    
    # Subscribe email if provided
    if email:
        sub_arn = subscribe_email(topic_arn, email)
        results['subscription_arn'] = sub_arn
        results['note'] = 'Check email to confirm subscription'
    
    # Update .env reminder
    print(f"\n⚠️  Add this to your .env file:")
    print(f"SNS_TOPIC_ARN={topic_arn}")
    
    return results


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='SNS Alert Setup')
    parser.add_argument('--setup', action='store_true', help='Create SNS topic')
    parser.add_argument('--email', type=str, help='Email to subscribe')
    parser.add_argument('--test', action='store_true', help='Send test alert')
    
    args = parser.parse_args()
    
    if args.setup:
        results = setup_sns(args.email)
        print(f"\nSetup complete: {results}")
        
    elif args.test:
        result = publish_alert(
            subject="MetricPulse Test Alert",
            message="This is a test alert from MetricPulse. If you received this, alerting is working correctly."
        )
        print(f"\nTest result: {result}")
        
    else:
        print("Usage:")
        print("  python sns_publisher.py --setup --email your@email.com")
        print("  python sns_publisher.py --test")
