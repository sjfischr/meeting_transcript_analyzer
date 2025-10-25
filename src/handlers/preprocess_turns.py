"""
Lambda handler for preprocessing meeting transcripts into atomic turns.

This function reads a raw meeting transcript and uses Bedrock to convert it
into structured turns with speaker identification, timestamps, and turn classification.
"""

import json
import os
import logging
from typing import Dict, Any

from common.bedrock_client import BedrockClient
from common.s3io import S3Client
from common.json_utils import validate_turns_schema, extract_json_from_text
from models.types import LambdaEvent, TurnsOutput

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_prompt_template() -> str:
    """Load the turns extraction prompt template."""
    # TODO: Load from S3 or embed here
    prompt_path = "/opt/prompts/01_turns.md"
    try:
        with open(prompt_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        # Fallback embedded prompt
        return """
Convert raw transcript text into structured turns with timestamps and speaker labels.
Output valid JSON with meeting_id, time_zone, and turns array.
Each turn must have: idx, start_ts, end_ts, speaker, type, question_likelihood, text.
        """.strip()


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for preprocessing transcripts into turns.
    
    Args:
        event: Lambda event containing meeting_id, input_key, output_key
        context: Lambda context (unused)
        
    Returns:
        Success/failure response with output location
    """
    try:
        # Parse event
        meeting_id = event['meeting_id']
        input_key = event['input_key']
        output_key = event['output_key']
        chunk_index = event.get('chunk_index', 0)  # For chunked processing
        
        logger.info(f"Processing transcript for meeting {meeting_id}, chunk {chunk_index}")
        
        # Initialize clients
        s3_client = S3Client()
        bedrock_client = BedrockClient()
        
        # Read transcript
        transcript_text = s3_client.read_text_file(input_key)
        logger.info(f"Read transcript: {len(transcript_text)} characters")
        
        # Load prompt template
        system_prompt = load_prompt_template()
        
        # Create user prompt with transcript
        user_prompt = f"""
Please process this meeting transcript into structured turns:

TRANSCRIPT:
{transcript_text}

MEETING_ID: {meeting_id}
TIME_ZONE: {os.getenv('TIME_ZONE', 'America/New_York')}

Output valid JSON following the schema specified in the system prompt.
        """.strip()
        
        # Call Bedrock
        logger.info("Calling Bedrock to process transcript")
        response = bedrock_client.invoke_with_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=100000  # Increased for large transcripts - Claude can handle up to 200k output
        )
        
        # Validate response structure
        validation_errors = validate_turns_schema(response)
        if validation_errors:
            logger.error(f"Validation errors: {validation_errors}")
            raise ValueError(f"Invalid response format: {validation_errors}")
            
        # Write output to S3
        s3_client.write_json_file(output_key, response)
        logger.info(f"Successfully wrote turns to {output_key}")
        
        return {
            'statusCode': 200,
            'meeting_id': meeting_id,
            'chunk_index': chunk_index,
            'output_key': output_key,
            'turn_count': len(response.get('turns', [])),
            'validation_status': 'valid'
        }
        
    except Exception as e:
        logger.error(f"Error processing transcript: {e}")
        return {
            'statusCode': 500,
            'error': str(e),
            'meeting_id': event.get('meeting_id', 'unknown')
        }