"""
Lambda handler for generating calendar events (ICS format).

This function reads the Q&A pairs and meeting minutes to extract
calendar events, deadlines, and scheduled items for ICS generation.
"""

import json
import os
import logging
from typing import Dict, Any

from common.bedrock_client import BedrockClient
from common.s3io import S3Client
from common.json_utils import validate_json_structure
from models.types import LambdaEvent, CalendarOutput

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_prompt_template() -> str:
    """Load the calendar events generation prompt template."""
    # TODO: Load from S3 or embed here
    prompt_path = "/opt/prompts/05_ics.md"
    try:
        with open(prompt_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        # Fallback embedded prompt
        return """
Extract actionable calendar events from meeting content.
Output valid JSON with meeting_id and calendar_events array.
Only include events with specific dates or clear timing.
        """.strip()


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for generating calendar events.
    
    Args:
        event: Lambda event containing meeting_id, input_key, output_key
        context: Lambda context (unused)
        
    Returns:
        Success/failure response with output location
    """
    try:
        # Parse event
        meeting_id = event['meeting_id']
        input_key = event['input_key']  # minutes.json (or qa_pairs.json)
        output_key = event['output_key']  # calendar.json
        
        logger.info(f"Generating calendar events for meeting {meeting_id}")
        
        # Initialize clients
        s3_client = S3Client()
        bedrock_client = BedrockClient()
        
        # Read minutes or Q&A data
        input_data = s3_client.read_json_file(input_key)
        logger.info(f"Read input data from {input_key}")
        
        # Load prompt template
        system_prompt = load_prompt_template()
        
        # Create user prompt with input data
        user_prompt = f"""
Please extract calendar events, deadlines, and scheduled items from this meeting data:

MEETING DATA:
{json.dumps(input_data, indent=2)}

MEETING_ID: {meeting_id}
TIME_ZONE: {os.getenv('TIME_ZONE', 'America/New_York')}

Only create events for items with specific dates or clear timing information.
Output valid JSON following the schema specified in the system prompt.
        """.strip()
        
        # Call Bedrock
        logger.info("Calling Bedrock to extract calendar events")
        response = bedrock_client.invoke_with_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=6000
        )
        
        # Basic validation
        validation_errors = validate_json_structure(response, ["meeting_id", "calendar_events"])
        if validation_errors:
            logger.error(f"Validation errors: {validation_errors}")
            raise ValueError(f"Invalid response format: {validation_errors}")
            
        # Write output to S3
        s3_client.write_json_file(output_key, response)
        logger.info(f"Successfully wrote calendar events to {output_key}")
        
        # Count events by type
        events = response.get('calendar_events', [])
        event_types = {}
        for event in events:
            event_type = event.get('type', 'unknown')
            event_types[event_type] = event_types.get(event_type, 0) + 1
        
        return {
            'statusCode': 200,
            'meeting_id': meeting_id,
            'output_key': output_key,
            'event_count': len(events),
            'event_types': event_types,
            'validation_status': 'valid'
        }
        
    except Exception as e:
        logger.error(f"Error generating calendar events: {e}")
        return {
            'statusCode': 500,
            'error': str(e),
            'meeting_id': event.get('meeting_id', 'unknown')
        }