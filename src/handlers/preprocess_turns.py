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


ALLOWED_TURN_TYPES = {"question", "answer", "followup", "monologue", "housekeeping"}
TURN_TYPE_SYNONYMS = {
    "statement": "monologue",
    "comment": "monologue",
    "discussion": "monologue",
    "context": "monologue",
    "other": "monologue",
    "response": "answer",
    "reply": "answer",
    "follow-up": "followup",
    "follow up": "followup",
    "questioning": "question"
}


def normalize_turn_output(payload: Dict[str, Any]) -> None:
    """Normalize model output to match expected schema values."""
    turns: Any = payload.get("turns")  # type: ignore[assignment]
    if not isinstance(turns, list):
        return

    for turn in turns:
        if not isinstance(turn, dict):
            continue

        raw_type = turn.get("type")
        normalized_type = None
        if isinstance(raw_type, str):
            type_key = raw_type.strip().lower()
            if type_key in ALLOWED_TURN_TYPES:
                normalized_type = type_key
            elif type_key in TURN_TYPE_SYNONYMS:
                normalized_type = TURN_TYPE_SYNONYMS[type_key]
            else:
                logger.warning("Unknown turn type '%s' - defaulting to 'monologue'", raw_type)
                normalized_type = "monologue"
        else:
            logger.debug("Turn missing string type value; defaulting to 'monologue'")
            normalized_type = "monologue"

        turn["type"] = normalized_type

        if "question_likelihood" in turn:
            try:
                likelihood = float(turn["question_likelihood"])
                if likelihood < 0:
                    likelihood = 0.0
                elif likelihood > 1:
                    likelihood = 1.0
                turn["question_likelihood"] = likelihood
            except (TypeError, ValueError):
                logger.warning("Invalid question_likelihood '%s' - defaulting to 0.0", turn.get("question_likelihood"))
                turn["question_likelihood"] = 0.0


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

        # Normalize and validate response structure
        normalize_turn_output(response)
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