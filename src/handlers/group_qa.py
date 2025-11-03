"""
Lambda handler for grouping turns into Q&A pairs and discussions.

This function reads the structured turns and uses Bedrock to group them into
coherent Q&A exchanges, monologues, and discussion segments.
"""

import json
import os
import logging
from typing import Dict, Any

from common.bedrock_client import BedrockClient
from common.s3io import S3Client
from common.json_utils import validate_qa_pairs_schema
from models.types import LambdaEvent, QAPairsOutput

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


ALLOWED_QA_GROUP_TYPES = {"qa_exchange", "monologue", "discussion", "housekeeping"}
QA_TYPE_SYNONYMS = {
    "q&a": "qa_exchange",
    "qa": "qa_exchange",
    "qa exchange": "qa_exchange",
    "question-answer": "qa_exchange",
    "question/answer": "qa_exchange",
    "question and answer": "qa_exchange",
    "q and a": "qa_exchange"
}

ROLE_SYNONYMS = {
    "follow-up": "followup",
    "follow up": "followup",
    "followup": "followup",
    "contextual": "context",
    "questioning": "question",
    "answering": "answer"
}


def normalize_qa_output(payload: Dict[str, Any]) -> None:
    """Normalize QA group structure before validation."""
    qa_pairs = payload.get("qa_pairs")
    if not isinstance(qa_pairs, list):
        return

    for index, qa_pair in enumerate(qa_pairs, start=1):
        if not isinstance(qa_pair, dict):
            continue

        raw_type = qa_pair.get("type")
        normalized_type = None
        if isinstance(raw_type, str):
            type_key = raw_type.strip().lower()
            if type_key in ALLOWED_QA_GROUP_TYPES:
                normalized_type = type_key
            elif type_key in QA_TYPE_SYNONYMS:
                normalized_type = QA_TYPE_SYNONYMS[type_key]
                logger.info(
                    "Remapping QA pair type '%s' to '%s' (group_id=%s)",
                    raw_type,
                    normalized_type,
                    qa_pair.get("group_id", index)
                )
            else:
                logger.warning(
                    "Unknown QA pair type '%s' (group_id=%s) - defaulting to 'discussion'",
                    raw_type,
                    qa_pair.get("group_id", index)
                )
                normalized_type = "discussion"
        else:
            logger.debug("Missing QA pair type for group index %d; defaulting to 'discussion'", index)
            normalized_type = "discussion"

        qa_pair["type"] = normalized_type

        raw_group_id = qa_pair.get("group_id")
        if isinstance(raw_group_id, int):
            qa_pair["group_id"] = raw_group_id
        elif raw_group_id is None:
            qa_pair["group_id"] = index
        else:
            try:
                qa_pair["group_id"] = int(raw_group_id)
            except (TypeError, ValueError):
                qa_pair["group_id"] = index

        turns = qa_pair.get("turns")
        if isinstance(turns, list):
            for turn in turns:
                if not isinstance(turn, dict):
                    continue
                raw_role = turn.get("role")
                if isinstance(raw_role, str):
                    role_key = raw_role.strip().lower()
                    normalized_role = ROLE_SYNONYMS.get(role_key, role_key)
                    turn["role"] = normalized_role



def load_prompt_template() -> str:
    """Load the Q&A grouping prompt template."""
    # TODO: Load from S3 or embed here
    prompt_path = "/opt/prompts/02_qa_grouper.md"
    try:
        with open(prompt_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        # Fallback embedded prompt
        return """
Group turns into coherent Q&A exchanges and standalone segments.
Output valid JSON with meeting_id and qa_pairs array.
Each group should have: group_id, type, topic, start_ts, end_ts, turns.
        """.strip()


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for grouping turns into Q&A pairs.
    
    Args:
        event: Lambda event containing meeting_id, input_key, output_key
        context: Lambda context (unused)
        
    Returns:
        Success/failure response with output location
    """
    try:
        # Parse event
        meeting_id = event['meeting_id']
        input_key = event['input_key']  # turns.json
        output_key = event['output_key']  # qa_pairs.json
        
        logger.info(f"Grouping Q&A pairs for meeting {meeting_id}")
        
        # Initialize clients
        s3_client = S3Client()
        bedrock_client = BedrockClient()
        
        # Read turns data
        turns_data = s3_client.read_json_file(input_key)
        logger.info(f"Read {len(turns_data.get('turns', []))} turns")
        
        # Load prompt template
        system_prompt = load_prompt_template()
        
        # Create user prompt with turns data
        user_prompt = f"""
Please group these meeting turns into coherent Q&A exchanges:

TURNS DATA:
{json.dumps(turns_data, indent=2)}

Group related turns that form Q&A patterns, discussions, or standalone monologues.
Output valid JSON following the schema specified in the system prompt.
        """.strip()
        
        # Call Bedrock
        logger.info("Calling Bedrock to group Q&A pairs")
        response = bedrock_client.invoke_with_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=8000
        )
        
        normalize_qa_output(response)

        # Validate response structure
        validation_errors = validate_qa_pairs_schema(response)
        if validation_errors:
            logger.error(f"Validation errors: {validation_errors}")
            raise ValueError(f"Invalid response format: {validation_errors}")
            
        # Write output to S3
        s3_client.write_json_file(output_key, response)
        logger.info(f"Successfully wrote Q&A pairs to {output_key}")
        
        return {
            'statusCode': 200,
            'meeting_id': meeting_id,
            'output_key': output_key,
            'qa_group_count': len(response.get('qa_pairs', [])),
            'validation_status': 'valid'
        }
        
    except Exception as e:
        logger.error(f"Error grouping Q&A pairs: {e}")
        return {
            'statusCode': 500,
            'error': str(e),
            'meeting_id': event.get('meeting_id', 'unknown')
        }