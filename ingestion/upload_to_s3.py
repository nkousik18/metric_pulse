"""
Upload raw CSV files to S3 bucket.
"""

import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.logging_config import setup_logger

load_dotenv()

logger = setup_logger(__name__)


def get_s3_client():
    """Create and return S3 client."""
    try:
        client = boto3.client(
            's3',
            region_name=os.getenv('AWS_REGION'),
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        logger.info("S3 client created successfully")
        return client
    except Exception as e:
        logger.error(f"Failed to create S3 client: {e}")
        raise


def upload_file(s3_client, file_path: Path, bucket: str, s3_key: str) -> bool:
    """
    Upload a single file to S3.
    
    Args:
        s3_client: Boto3 S3 client
        file_path: Local path to file
        bucket: S3 bucket name
        s3_key: S3 object key (path in bucket)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        logger.info(f"Uploading {file_path.name} ({file_size_mb:.2f} MB) to s3://{bucket}/{s3_key}")
        
        s3_client.upload_file(str(file_path), bucket, s3_key)
        
        logger.info(f"Successfully uploaded {file_path.name}")
        return True
        
    except ClientError as e:
        logger.error(f"Failed to upload {file_path.name}: {e}")
        return False
    except FileNotFoundError:
        logger.error(f"File not found: {file_path}")
        return False


def upload_raw_data(data_dir: str = "data/raw") -> dict:
    """
    Upload all CSV files from data directory to S3.
    
    Args:
        data_dir: Path to directory containing raw CSV files
    
    Returns:
        Dictionary with upload results
    """
    results = {"success": [], "failed": []}
    
    bucket = os.getenv('S3_BUCKET_NAME')
    if not bucket:
        logger.error("S3_BUCKET_NAME not set in environment")
        raise ValueError("S3_BUCKET_NAME environment variable required")
    
    data_path = Path(__file__).parent.parent / data_dir
    
    if not data_path.exists():
        logger.error(f"Data directory not found: {data_path}")
        raise FileNotFoundError(f"Directory not found: {data_path}")
    
    csv_files = list(data_path.glob("*.csv"))
    
    if not csv_files:
        logger.warning(f"No CSV files found in {data_path}")
        return results
    
    logger.info(f"Found {len(csv_files)} CSV files to upload")
    
    s3_client = get_s3_client()
    
    for file_path in csv_files:
        s3_key = f"raw/{file_path.name}"
        
        if upload_file(s3_client, file_path, bucket, s3_key):
            results["success"].append(file_path.name)
        else:
            results["failed"].append(file_path.name)
    
    logger.info(f"Upload complete: {len(results['success'])} succeeded, {len(results['failed'])} failed")
    
    return results


def verify_uploads() -> list:
    """
    Verify files exist in S3 bucket.
    
    Returns:
        List of objects in raw/ prefix
    """
    bucket = os.getenv('S3_BUCKET_NAME')
    s3_client = get_s3_client()
    
    try:
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix="raw/")
        
        if 'Contents' not in response:
            logger.warning("No files found in raw/ prefix")
            return []
        
        files = [obj['Key'] for obj in response['Contents']]
        logger.info(f"Found {len(files)} files in s3://{bucket}/raw/")
        
        for f in files:
            logger.debug(f"  - {f}")
        
        return files
        
    except ClientError as e:
        logger.error(f"Failed to list S3 objects: {e}")
        raise


if __name__ == "__main__":
    logger.info("Starting raw data upload to S3")
    
    try:
        results = upload_raw_data()
        
        print("\n" + "=" * 50)
        print("UPLOAD SUMMARY")
        print("=" * 50)
        print(f"Successful: {len(results['success'])}")
        for f in results['success']:
            print(f"  ✓ {f}")
        
        if results['failed']:
            print(f"\nFailed: {len(results['failed'])}")
            for f in results['failed']:
                print(f"  ✗ {f}")
        
        print("\nVerifying uploads...")
        verify_uploads()
        
    except Exception as e:
        logger.error(f"Upload process failed: {e}")
        sys.exit(1)
