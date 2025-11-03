"""
Lambda handler for generating meeting minutes and action items.

This function reads the Q&A pairs and uses Bedrock to generate formal
meeting minutes with agenda items, decisions, and action items.
"""

import json
import os
import logging
from typing import Dict, Any

from common.bedrock_client import BedrockClient
from common.s3io import S3Client
from common.json_utils import validate_minutes_schema
from models.types import LambdaEvent, MinutesOutput

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def normalize_minutes_output(payload: Dict[str, Any]) -> None:
    """Ensure minutes output has required fields and consistent defaults."""
    minutes = payload.get("minutes")
    if not isinstance(minutes, dict):
        return

    meeting_info = minutes.get("meeting_info")
    if isinstance(meeting_info, dict):
        for field in ("start_time", "end_time"):
            value = meeting_info.get(field)
            if not isinstance(value, str) or not value.strip():
                logger.info("Filling missing %s in meeting_info with 'TBD'", field)
                meeting_info[field] = "TBD"

    action_items = minutes.get("action_items")
    if not isinstance(action_items, list):
        return

    for index, item in enumerate(action_items, start=1):
        if not isinstance(item, dict):
            continue

        # Ensure numeric ID and stable defaults for downstream consumers.
        raw_id = item.get("id")
        if isinstance(raw_id, int):
            item["id"] = raw_id
        else:
            try:
                item["id"] = int(raw_id) if raw_id is not None else index
            except (TypeError, ValueError):
                logger.info("Assigning missing action item id for index %d", index)
                item["id"] = index

        description = item.get("description")
        if not isinstance(description, str) or not description.strip():
            fallback = None
            for candidate_key in ("details", "summary", "text", "notes"):
                candidate = item.get(candidate_key)
                if isinstance(candidate, str) and candidate.strip():
                    fallback = candidate.strip()
                    break
            if fallback is None:
                fallback = f"Action item {item['id']}"
            logger.info(
                "Filling missing description for action item %d using fallback", item["id"]
            )
            item["description"] = fallback

        # Fill defaults that the prompt might omit.
        item.setdefault("status", "open")
        item.setdefault("priority", "medium")
        item.setdefault("due_date", "TBD")



def load_prompt_template() -> str:
    """Load the minutes & action items prompt template."""
    # TODO: Load from S3 or embed here
    prompt_path = "/opt/prompts/03_minutes_actions.md"
    try:
        with open(prompt_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        # Fallback embedded prompt
        return """
Generate formal meeting minutes with action items from Q&A pairs.
Output valid JSON with meeting_id and minutes object.
Include meeting_info, agenda_items, action_items, announcements, next_meeting.
        """.strip()


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for generating meeting minutes and action items.
    
    Args:
        event: Lambda event containing meeting_id, input_key, output_key
        context: Lambda context (unused)
        
    Returns:
        Success/failure response with output location
    """
    try:
        # Parse event
        meeting_id = event['meeting_id']
        input_key = event['input_key']  # qa_pairs.json
        output_key = event['output_key']  # minutes.json
        
        logger.info(f"Generating minutes for meeting {meeting_id}")
        
        # Initialize clients
        s3_client = S3Client()
        bedrock_client = BedrockClient()
        
        # Read Q&A pairs data
        qa_data = s3_client.read_json_file(input_key)
        logger.info(f"Read {len(qa_data.get('qa_pairs', []))} Q&A groups")
        
        # Load prompt template
        system_prompt = load_prompt_template()
        
        # Create user prompt with Q&A data
        user_prompt = f"""
Please generate formal meeting minutes and action items from these Q&A exchanges:

Q&A DATA:
{json.dumps(qa_data, indent=2)}

MEETING_ID: {meeting_id}
TIME_ZONE: {os.getenv('TIME_ZONE', 'America/New_York')}

Generate comprehensive minutes with proper formatting and clear action items.
Output valid JSON following the schema specified in the system prompt.
        """.strip()
        
        # Call Bedrock
        logger.info("Calling Bedrock to generate minutes")
        response = bedrock_client.invoke_with_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=8000
        )
        
        normalize_minutes_output(response)

        # Validate response structure
        validation_errors = validate_minutes_schema(response)
        if validation_errors:
            logger.error(f"Validation errors: {validation_errors}")
            raise ValueError(f"Invalid response format: {validation_errors}")
            
        # Write output to S3
        s3_client.write_json_file(output_key, response)
        logger.info(f"Successfully wrote minutes to {output_key}")
        
        # Count action items
        action_count = len(response.get('minutes', {}).get('action_items', []))
        agenda_count = len(response.get('minutes', {}).get('agenda_items', []))
        
        return {
            'statusCode': 200,
            'meeting_id': meeting_id,
            'output_key': output_key,
            'action_item_count': action_count,
            'agenda_item_count': agenda_count,
            'validation_status': 'valid'
        }
        
    except Exception as e:
        logger.error(f"Error generating minutes: {e}")
        return {
            'statusCode': 500,
            'error': str(e),
            'meeting_id': event.get('meeting_id', 'unknown')
        }