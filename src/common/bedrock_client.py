"""
Amazon Bedrock client utilities for GRiST meeting pipeline.

Provides a centralized interface for calling Bedrock models with proper
error handling, retry logic, and response parsing.
"""

import json
import os
import time
from typing import Dict, Any, Optional
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError
import logging

logger = logging.getLogger(__name__)


class BedrockClient:
    """Client for interacting with Amazon Bedrock inference."""
    
    def __init__(self, region: Optional[str] = None, inference_profile_arn: Optional[str] = None):
        """
        Initialize Bedrock client.
        
        Args:
            region: AWS region (defaults to environment variable)
            inference_profile_arn: Bedrock inference profile ARN (defaults to environment variable)
        """
        self.region = region or os.getenv('REGION', 'us-east-1')
        self.inference_profile_arn = inference_profile_arn or os.getenv('INFERENCE_PROFILE_ARN')
        
        if not self.inference_profile_arn:
            raise ValueError("INFERENCE_PROFILE_ARN environment variable is required")
        
        # Configure boto3 client with extended timeouts for large transcripts
        # Disable standard retries - we'll handle throttling manually with exponential backoff
        config = Config(
            read_timeout=900,  # 15 minutes - match Lambda timeout
            connect_timeout=60,
            retries={'max_attempts': 0}  # Disable standard retries, we handle throttling manually
        )
        
        self.client = boto3.client('bedrock-runtime', region_name=self.region, config=config)
        
    def invoke_model(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, 
                     max_retries: int = 5) -> str:
        """
        Invoke Bedrock model with system and user prompts, with exponential backoff for throttling.
        
        Args:
            system_prompt: System context/instructions for the model
            user_prompt: User's actual prompt/question
            max_tokens: Maximum tokens in response
            max_retries: Maximum retry attempts for throttling (default 5)
            
        Returns:
            Model response text
            
        Raises:
            Exception: If model invocation fails after all retries
        """
        # Anthropic Claude message format for Bedrock
        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user", 
                    "content": user_prompt
                }
            ]
        }
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = self.client.invoke_model(
                    modelId=self.inference_profile_arn,
                    body=json.dumps(request_body),
                    contentType='application/json',
                    accept='application/json'
                )
                
                response_body = json.loads(response['body'].read())
                
                if 'content' in response_body and response_body['content']:
                    response_text = response_body['content'][0].get('text', '')
                    if not response_text or not response_text.strip():
                        logger.warning("Bedrock returned empty response text; retrying")
                        last_error = Exception("Model returned empty response text")
                        raise last_error
                    return response_text
                else:
                    raise Exception("Unexpected response format from Bedrock")
                    
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', '')
                
                if error_code == 'ThrottlingException':
                    # Exponential backoff with jitter
                    wait_time = min(60, (2 ** attempt) + (time.time() % 1))  # Max 60s wait
                    logger.warning(f"Bedrock throttled (attempt {attempt + 1}/{max_retries}), "
                                 f"waiting {wait_time:.2f}s before retry...")
                    time.sleep(wait_time)
                    last_error = e
                    continue
                elif error_code in ['ServiceUnavailableException', 'InternalServerException']:
                    # Temporary service errors - retry with backoff
                    wait_time = min(30, (2 ** attempt))
                    logger.warning(f"Bedrock service error (attempt {attempt + 1}/{max_retries}), "
                                 f"waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    last_error = e
                    continue
                else:
                    # Other client errors - don't retry
                    logger.error(f"Bedrock client error: {e}")
                    raise Exception(f"Bedrock invocation failed: {e}")
                    
            except BotoCoreError as e:
                logger.error(f"Boto core error: {e}")
                raise Exception(f"AWS SDK error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error invoking Bedrock: {e}")
                last_error = e
        
        # All retries exhausted
        logger.error(f"Bedrock invocation failed after {max_retries} attempts")
        raise Exception(f"Bedrock invocation failed after {max_retries} retries: {last_error}")
            
    def invoke_with_json_response(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> Dict[str, Any]:
        """
        Invoke model and parse response as JSON.
        
        Args:
            system_prompt: System context/instructions  
            user_prompt: User's prompt
            max_tokens: Maximum response tokens
            
        Returns:
            Parsed JSON response
            
        Raises:
            Exception: If invocation fails or response is not valid JSON
        """
        response_text = self.invoke_model(system_prompt, user_prompt, max_tokens)
        
        # First try direct JSON parsing
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.warning(f"Direct JSON parse failed: {e}. Attempting to extract JSON from text...")
            
            # Try to extract JSON from markdown code blocks or mixed content
            # Remove markdown code blocks if present
            if '```json' in response_text:
                # Extract JSON from markdown code block
                start = response_text.find('```json') + 7
                end = response_text.find('```', start)
                if end != -1:
                    response_text = response_text[start:end].strip()
            elif '```' in response_text:
                # Generic code block
                start = response_text.find('```') + 3
                end = response_text.find('```', start)
                if end != -1:
                    response_text = response_text[start:end].strip()
            
            # Try parsing again after cleaning
            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                # Last resort: find JSON object boundaries
                start_idx = response_text.find('{')
                if start_idx != -1:
                    # Find matching closing brace
                    brace_count = 0
                    for i, char in enumerate(response_text[start_idx:]):
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                try:
                                    json_str = response_text[start_idx:start_idx + i + 1]
                                    return json.loads(json_str)
                                except json.JSONDecodeError:
                                    continue
                
                # If all parsing attempts fail, log and raise
                logger.error(f"Failed to parse JSON response after all attempts. First 1000 chars: {response_text[:1000]}")
                logger.error(f"Last 1000 chars: {response_text[-1000:]}")
                raise Exception(f"Model response is not valid JSON: {e}")