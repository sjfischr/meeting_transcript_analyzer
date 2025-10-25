"""
Lambda handler for generating meeting summaries.

This function reads the Q&A pairs and uses Bedrock to generate multiple
types of summaries: executive, detailed, highlights, and sentiment analysis.
"""

import json
import os
import logging
from typing import Dict, Any

from common.bedrock_client import BedrockClient
from common.s3io import S3Client
from common.json_utils import validate_json_structure
from models.types import LambdaEvent, SummariesOutput

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_prompt_template() -> str:
    """Load the summaries generation prompt template."""
    # TODO: Load from S3 or embed here
    prompt_path = "/opt/prompts/04_summaries.md"
    try:
        with open(prompt_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        # Fallback embedded prompt
        return """
Generate multiple types of meeting summaries for different audiences.
Output valid JSON with meeting_id and summaries object.
Include executive_summary, detailed_summary, key_highlights, topics_covered, sentiment_analysis.
        """.strip()


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for generating meeting summaries.
    
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
        output_key = event['output_key']  # summaries.json
        
        logger.info(f"Generating summaries for meeting {meeting_id}")
        
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
Please generate comprehensive meeting summaries from these Q&A exchanges:

Q&A DATA:
{json.dumps(qa_data, indent=2)}

MEETING_ID: {meeting_id}

Create executive summary, detailed summary, key highlights, topic coverage, and sentiment analysis.
Output valid JSON following the schema specified in the system prompt.
        """.strip()
        
        # Call Bedrock
        logger.info("Calling Bedrock to generate summaries")
        response = bedrock_client.invoke_with_json_response(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=8000
        )
        
        # Basic validation
        validation_errors = validate_json_structure(response, ["meeting_id", "summaries"])
        if validation_errors:
            logger.error(f"Validation errors: {validation_errors}")
            raise ValueError(f"Invalid response format: {validation_errors}")
            
        # Write output to S3
        s3_client.write_json_file(output_key, response)
        logger.info(f"Successfully wrote summaries to {output_key}")
        
        # Count highlights and topics
        summaries = response.get('summaries', {})
        highlight_count = len(summaries.get('key_highlights', []))
        topic_count = len(summaries.get('topics_covered', []))
        
        return {
            'statusCode': 200,
            'meeting_id': meeting_id,
            'output_key': output_key,
            'highlight_count': highlight_count,
            'topic_count': topic_count,
            'validation_status': 'valid'
        }
        
    except Exception as e:
        logger.error(f"Error generating summaries: {e}")
        return {
            'statusCode': 500,
            'error': str(e),
            'meeting_id': event.get('meeting_id', 'unknown')
        }