"""
JSON utilities for schema validation and data processing.

Provides validation against JSON schemas and helper functions for
working with structured data in the meeting pipeline.
"""

import json
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


def validate_json_structure(data: Dict[str, Any], required_fields: List[str]) -> List[str]:
    """
    Validate that JSON data contains required fields.
    
    Args:
        data: JSON data to validate
        required_fields: List of required field names
        
    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    
    if not isinstance(data, dict):
        errors.append("Data must be a JSON object")
        return errors
        
    for field in required_fields:
        if field not in data:
            errors.append(f"Missing required field: {field}")
        elif data[field] is None:
            errors.append(f"Field '{field}' cannot be null")
            
    return errors


def validate_turns_schema(data: Dict[str, Any]) -> List[str]:
    """
    Validate turns JSON against expected schema.
    
    Args:
        data: Turns JSON data
        
    Returns:
        List of validation errors
    """
    errors = validate_json_structure(data, ["meeting_id", "time_zone", "turns"])
    
    if "turns" in data and isinstance(data["turns"], list):
        for i, turn in enumerate(data["turns"]):
            if not isinstance(turn, dict):
                errors.append(f"Turn {i} must be an object")
                continue
                
            turn_errors = validate_json_structure(turn, [
                "idx", "start_ts", "end_ts", "speaker", "type", "question_likelihood", "text"
            ])
            for error in turn_errors:
                errors.append(f"Turn {i}: {error}")
                
            # Validate turn type
            if "type" in turn and turn["type"] not in ["question", "answer", "followup", "monologue", "housekeeping"]:
                errors.append(f"Turn {i}: Invalid type '{turn['type']}'")
                
            # Validate question likelihood range
            if "question_likelihood" in turn:
                try:
                    likelihood = float(turn["question_likelihood"])
                    if likelihood < 0 or likelihood > 1:
                        errors.append(f"Turn {i}: question_likelihood must be between 0 and 1")
                except (ValueError, TypeError):
                    errors.append(f"Turn {i}: question_likelihood must be a number")
                    
    return errors


def validate_qa_pairs_schema(data: Dict[str, Any]) -> List[str]:
    """
    Validate Q&A pairs JSON against expected schema.
    
    Args:
        data: Q&A pairs JSON data
        
    Returns:
        List of validation errors
    """
    errors = validate_json_structure(data, ["meeting_id", "qa_pairs"])
    
    if "qa_pairs" in data and isinstance(data["qa_pairs"], list):
        for i, pair in enumerate(data["qa_pairs"]):
            if not isinstance(pair, dict):
                errors.append(f"QA pair {i} must be an object")
                continue
                
            pair_errors = validate_json_structure(pair, [
                "group_id", "type", "topic", "start_ts", "end_ts", "turns"
            ])
            for error in pair_errors:
                errors.append(f"QA pair {i}: {error}")
                
            # Validate type
            if "type" in pair and pair["type"] not in ["qa_exchange", "monologue", "discussion", "housekeeping"]:
                errors.append(f"QA pair {i}: Invalid type '{pair['type']}'")
                
    return errors


def validate_minutes_schema(data: Dict[str, Any]) -> List[str]:
    """
    Validate minutes JSON against expected schema.
    
    Args:
        data: Minutes JSON data
        
    Returns:
        List of validation errors
    """
    errors = validate_json_structure(data, ["meeting_id", "minutes"])
    
    if "minutes" in data and isinstance(data["minutes"], dict):
        minutes = data["minutes"]
        
        # Validate meeting_info
        if "meeting_info" in minutes:
            info_errors = validate_json_structure(minutes["meeting_info"], [
                "title", "date", "start_time", "end_time"
            ])
            for error in info_errors:
                errors.append(f"Meeting info: {error}")
                
        # Validate action_items
        if "action_items" in minutes and isinstance(minutes["action_items"], list):
            for i, item in enumerate(minutes["action_items"]):
                item_errors = validate_json_structure(item, [
                    "id", "description", "status", "priority"
                ])
                for error in item_errors:
                    errors.append(f"Action item {i}: {error}")
                    
    return errors


def sanitize_json_string(text: str) -> str:
    """
    Clean up a string to be safe for JSON serialization.
    
    Args:
        text: Input text
        
    Returns:
        Sanitized text safe for JSON
    """
    # Remove or escape characters that might break JSON
    # TODO: Implement comprehensive sanitization
    return text.strip().replace('\n', ' ').replace('\r', ' ')


def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Attempt to extract JSON from mixed text content.
    
    Useful for parsing model responses that might contain 
    JSON surrounded by other text.
    
    Args:
        text: Text that may contain JSON
        
    Returns:
        Parsed JSON data or None if no valid JSON found
    """
    # Look for JSON object boundaries
    start_idx = text.find('{')
    if start_idx == -1:
        return None
        
    # Find matching closing brace
    brace_count = 0
    for i, char in enumerate(text[start_idx:]):
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0:
                try:
                    json_str = text[start_idx:start_idx + i + 1]
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    continue
                    
    return None


def count_records(data: Dict[str, Any], record_key: str) -> int:
    """
    Count records in a JSON structure.
    
    Args:
        data: JSON data
        record_key: Key containing the list/array of records
        
    Returns:
        Number of records
    """
    if record_key in data and isinstance(data[record_key], list):
        return len(data[record_key])
    return 0