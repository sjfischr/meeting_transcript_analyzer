"""
Lambda handler for triggering the Step Functions pipeline from S3 events.

This function receives EventBridge notifications when .txt files are uploaded
to the S3 bucket and starts the processing pipeline automatically.
"""

import json
import os
import logging
import re
from typing import Dict, Any
from datetime import datetime
from urllib.parse import unquote_plus

import boto3

# Configure logging for Lambda (ensure INFO-level visibility even if root is WARNING)
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)


def extract_meeting_info(s3_key: str) -> Dict[str, str]:
    """
    Extract meeting information from S3 key.
    
    Expected format: meetings/{meeting_id}/transcript.txt
    or: meetings/{meeting_id}/{filename}.txt
    or: {filename}.txt (root level - will use filename as meeting_id)
    
    Args:
        s3_key: S3 object key
        
    Returns:
        Dict with meeting_id and base_path
    """
    # Remove .txt extension
    base_key = s3_key.rsplit('.txt', 1)[0]
    
    # Split path into parts
    parts = base_key.split('/')
    
    if len(parts) >= 2 and parts[0] == 'meetings':
        # Format: meetings/{meeting_id}/...
        meeting_id = parts[1]
        base_path = f"meetings/{meeting_id}/"
    else:
        # Use filename as meeting_id (NO timestamp for idempotency)
        # Same file = same meeting_id = idempotent execution
        filename = parts[-1]
        meeting_id = filename
        base_path = f"meetings/{meeting_id}/"
    
    return {
        'meeting_id': meeting_id,
        'base_path': base_path
    }


def sanitize_execution_name(raw_name: str) -> str:
    """Sanitize a string so it can be used as Step Functions execution name."""
    sanitized = re.sub(r"[^A-Za-z0-9\-_]+", "-", raw_name)
    sanitized = sanitized.strip('-')
    if not sanitized:
        sanitized = f"meeting-{int(datetime.utcnow().timestamp())}"
    return sanitized[:80]


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler to trigger Step Functions from S3 EventBridge events.
    
    Args:
        event: EventBridge event containing S3 object details
        context: Lambda context
        
    Returns:
        Response with execution details
    """
    try:
        logger.info(f"Received event: {json.dumps(event)}")
        
        # Extract S3 details from EventBridge event
        detail = event.get('detail', {})
        bucket_name = detail.get('bucket', {}).get('name')
        raw_key = detail.get('object', {}).get('key')
        
        if not bucket_name or not raw_key:
            logger.error("Missing bucket or key in event")
            return {
                'statusCode': 400,
                'error': 'Missing required S3 information in event'
            }

        s3_key = unquote_plus(raw_key)
        if raw_key != s3_key:
            logger.info("Decoded S3 key from '%s' to '%s'", raw_key, s3_key)
        
        logger.info(f"Processing file: s3://{bucket_name}/{s3_key}")
        
        # Extract meeting information
        meeting_info = extract_meeting_info(s3_key)
        meeting_id = meeting_info['meeting_id']
        base_path = meeting_info['base_path']
        
        logger.info(f"Extracted meeting_id: {meeting_id}, base_path: {base_path}")
        
        # Build Step Functions input
        sfn_input = {
            'meeting_id': meeting_id,
            'input_key': s3_key,
            'output_key': base_path,
            'bucket': bucket_name,
            'source_event': 's3-upload',
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Get state machine ARN from environment
        state_machine_arn = os.getenv('STATE_MACHINE_ARN')
        if not state_machine_arn:
            raise ValueError("STATE_MACHINE_ARN environment variable not set")
        
        # Start Step Functions execution
        sfn_client = boto3.client('stepfunctions')

        # Use meeting_id plus EventBridge event id so retries of the same event dedupe,
        # but new uploads of the same meeting_id still get a fresh execution name.
        event_id = event.get('id') or f"evt-{int(datetime.utcnow().timestamp())}"
        execution_name = sanitize_execution_name(f"{meeting_id}-{event_id[-24:]}")
        
        try:
            response = sfn_client.start_execution(
                stateMachineArn=state_machine_arn,
                name=execution_name,
                input=json.dumps(sfn_input)
            )
            
            logger.info(f"✅ Started NEW execution: {response['executionArn']}")
            
        except sfn_client.exceptions.ExecutionAlreadyExists:
            # Execution with this name already running - this is OK (idempotency working)
            logger.info(f"ℹ️ Execution '{execution_name}' already exists - ignoring duplicate S3 event")
            return {
                'statusCode': 200,
                'meeting_id': meeting_id,
                'message': 'Execution already running (duplicate S3 event ignored)',
                'execution_name': execution_name
            }
        
        return {
            'statusCode': 200,
            'meeting_id': meeting_id,
            'execution_arn': response['executionArn'],
            'input_key': s3_key,
            'output_key': base_path
        }
        
    except Exception as e:
        logger.error(f"Error triggering pipeline: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'error': str(e)
        }
