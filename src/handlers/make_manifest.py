"""
Lambda handler for generating processing manifest.

This function creates a comprehensive manifest of all processing outputs
with metadata, quality metrics, and validation status.
"""

import json
import os
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List

from common.s3io import S3Client
from common.json_utils import validate_json_structure, count_records
from models.types import LambdaEvent, ManifestOutput

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def calculate_quality_score(artifact_type: str, data: Dict[str, Any]) -> float:
    """
    Calculate a quality score for an artifact based on its content.
    
    Args:
        artifact_type: Type of artifact
        data: Artifact data
        
    Returns:
        Quality score between 0.0 and 1.0
    """
    # TODO: Implement more sophisticated quality scoring
    base_score = 0.8
    
    if artifact_type == "turns":
        turns = data.get('turns', [])
        if turns:
            # Higher score if turns have good speaker identification
            speaker_identified = sum(1 for t in turns if t.get('speaker', 'unknown') != 'unknown')
            speaker_ratio = speaker_identified / len(turns)
            base_score = 0.6 + (0.4 * speaker_ratio)
            
    elif artifact_type == "qa_pairs":
        qa_pairs = data.get('qa_pairs', [])
        if qa_pairs:
            # Higher score if groups have meaningful topics
            topics_present = sum(1 for qa in qa_pairs if qa.get('topic', '').strip())
            topic_ratio = topics_present / len(qa_pairs)
            base_score = 0.7 + (0.3 * topic_ratio)
            
    return min(1.0, base_score)


def assess_transcript_quality(turns_data: Dict[str, Any]) -> Dict[str, float]:
    """
    Assess overall transcript quality metrics.
    
    Args:
        turns_data: Turns data from preprocessing step
        
    Returns:
        Quality metrics dictionary
    """
    turns = turns_data.get('turns', [])
    
    if not turns:
        return {
            'transcript_clarity': 0.0,
            'speaker_identification': 0.0,
            'timestamp_accuracy': 1.0,  # Assume timestamps are accurate
            'content_completeness': 0.0
        }
    
    # Speaker identification quality
    identified_speakers = sum(1 for t in turns if t.get('speaker', 'unknown') != 'unknown')
    speaker_score = identified_speakers / len(turns) if turns else 0.0
    
    # Content completeness based on turn text length
    text_lengths = [len(t.get('text', '')) for t in turns]
    avg_length = sum(text_lengths) / len(text_lengths) if text_lengths else 0
    completeness_score = min(1.0, avg_length / 50)  # Assume 50 chars is reasonable minimum
    
    # Transcript clarity based on question likelihood confidence
    confidences = [t.get('question_likelihood', 0.5) for t in turns]
    # High confidence (near 0 or 1) indicates clear classification
    clarity_scores = [min(conf, 1.0 - conf) * 2 for conf in confidences]
    clarity_score = sum(clarity_scores) / len(clarity_scores) if clarity_scores else 0.5
    
    return {
        'transcript_clarity': clarity_score,
        'speaker_identification': speaker_score,
        'timestamp_accuracy': 0.9,  # Assume good timestamp accuracy
        'content_completeness': completeness_score
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for generating processing manifest.
    
    Args:
        event: Lambda event containing meeting_id and artifact keys
        context: Lambda context (unused)
        
    Returns:
        Success/failure response with manifest location
    """
    try:
        # Parse event - expect all artifact keys
        meeting_id = event['meeting_id']
        output_key = event['output_key']  # manifest.json
        
        # Artifact keys from parallel processing
        artifact_keys = {
            'turns': event.get('turns_key'),
            'qa_pairs': event.get('qa_pairs_key'), 
            'minutes': event.get('minutes_key'),
            'summaries': event.get('summaries_key'),
            'calendar': event.get('calendar_key')
        }
        
        logger.info(f"Generating manifest for meeting {meeting_id}")
        
        # Initialize S3 client
        s3_client = S3Client()
        
        # Processing timing
        end_time = datetime.now(timezone.utc)
        # TODO: Get actual start time from Step Functions input
        start_time = end_time  # Placeholder
        
        # Read and analyze all artifacts
        artifacts = []
        warnings = []
        
        # Read turns for quality assessment
        turns_data = None
        if artifact_keys['turns']:
            try:
                turns_data = s3_client.read_json_file(artifact_keys['turns'])
            except Exception as e:
                warnings.append(f"Could not read turns data: {e}")
        
        # Process each artifact
        for artifact_type, key in artifact_keys.items():
            if not key:
                warnings.append(f"Missing {artifact_type} artifact")
                continue
                
            try:
                # Read artifact data
                data = s3_client.read_json_file(key)
                size_bytes = s3_client.get_file_size(key)
                
                # Count records
                record_count = 0
                if artifact_type == "turns":
                    record_count = count_records(data, "turns")
                elif artifact_type == "qa_pairs":
                    record_count = count_records(data, "qa_pairs")
                elif artifact_type == "minutes":
                    action_items = data.get('minutes', {}).get('action_items', [])
                    record_count = len(action_items)
                elif artifact_type == "summaries":
                    highlights = data.get('summaries', {}).get('key_highlights', [])
                    record_count = len(highlights)
                elif artifact_type == "calendar":
                    record_count = count_records(data, "calendar_events")
                
                # Basic validation
                validation_errors = validate_json_structure(data, ["meeting_id"])
                validation_status = "valid" if not validation_errors else "invalid"
                if validation_errors:
                    warnings.extend([f"{artifact_type}: {err}" for err in validation_errors])
                
                # Calculate quality score
                quality_score = calculate_quality_score(artifact_type, data)
                
                # Add artifact info
                artifacts.append({
                    "filename": key.split('/')[-1],  # Just filename
                    "type": artifact_type,
                    "size_bytes": size_bytes,
                    "record_count": record_count,
                    "validation_status": validation_status,
                    "quality_score": quality_score,
                    "generation_time_seconds": 30,  # TODO: Track actual timing
                    "dependencies": ["transcript.txt"] if artifact_type == "turns" else [artifact_keys['turns']] if artifact_keys['turns'] else [],
                    "schema_version": "1.0"
                })
                
            except Exception as e:
                logger.error(f"Error processing {artifact_type}: {e}")
                warnings.append(f"Error processing {artifact_type}: {e}")
        
        # Generate quality metrics
        quality_metrics = assess_transcript_quality(turns_data) if turns_data else {
            'transcript_clarity': 0.5,
            'speaker_identification': 0.5,
            'timestamp_accuracy': 0.5,
            'content_completeness': 0.5
        }
        
        # Build manifest
        manifest_data = {
            "meeting_id": meeting_id,
            "manifest": {
                "processing_info": {
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat(),
                    "total_duration_seconds": 300,  # TODO: Calculate actual duration
                    "pipeline_version": "1.0.0",
                    "processing_status": "completed" if not warnings else "partial"
                },
                "source_info": {
                    "transcript_file": "transcript.txt",  # TODO: Get from event
                    "file_size_bytes": 50000,  # TODO: Get actual size
                    "transcript_length": "01:30:00",  # TODO: Calculate from turns
                    "estimated_speakers": 5,  # TODO: Calculate from turns
                    "language": "en"  # TODO: Detect or get from config
                },
                "artifacts": artifacts,
                "quality_metrics": quality_metrics,
                "warnings": warnings,
                "next_steps": [
                    "Review action items for completeness",
                    "Validate calendar events before scheduling",
                    "Distribute meeting minutes to attendees"
                ]
            }
        }
        
        # Write manifest to S3
        s3_client.write_json_file(output_key, manifest_data)
        logger.info(f"Successfully wrote manifest to {output_key}")
        
        return {
            'statusCode': 200,
            'meeting_id': meeting_id,
            'output_key': output_key,
            'artifact_count': len(artifacts),
            'warning_count': len(warnings),
            'processing_status': manifest_data['manifest']['processing_info']['processing_status']
        }
        
    except Exception as e:
        logger.error(f"Error generating manifest: {e}")
        return {
            'statusCode': 500,
            'error': str(e),
            'meeting_id': event.get('meeting_id', 'unknown')
        }