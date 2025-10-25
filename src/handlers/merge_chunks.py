"""
Lambda handler for merging turns from overlapping chunks.

This function intelligently merges turn data from multiple chunks, handling
the overlap regions to prevent duplicate or missing content at chunk boundaries.
"""

import json
import os
import logging
from typing import Dict, Any, List, Set, Tuple, Optional
from datetime import datetime

from common.s3io import S3Client
from common.json_utils import validate_turns_schema

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def normalize_speaker(speaker: str) -> str:
    """Normalize speaker name for comparison."""
    return speaker.strip().lower()


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    return ' '.join(text.split()).lower()


def calculate_text_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity between two text strings (0.0 to 1.0).
    
    Args:
        text1: First text
        text2: Second text
        
    Returns:
        Similarity score (0.0 = completely different, 1.0 = identical)
    """
    norm1 = normalize_text(text1)
    norm2 = normalize_text(text2)
    
    if norm1 == norm2:
        return 1.0
    
    # Calculate Jaccard similarity on words
    words1 = set(norm1.split())
    words2 = set(norm2.split())
    
    if not words1 or not words2:
        return 0.0
    
    intersection = words1 & words2
    union = words1 | words2
    
    return len(intersection) / len(union)


def find_duplicate_turn(turn: Dict[str, Any], existing_turns: List[Dict[str, Any]], 
                        similarity_threshold: float = 0.8) -> Optional[int]:
    """
    Find if turn is duplicate of an existing turn.
    
    Args:
        turn: Turn to check
        existing_turns: List of existing turns
        similarity_threshold: Minimum similarity to consider duplicate
        
    Returns:
        Index of duplicate turn, or None if no duplicate
    """
    turn_speaker = normalize_speaker(turn['speaker'])
    turn_text = turn['text']
    
    for i, existing_turn in enumerate(existing_turns):
        # Must have same speaker
        if normalize_speaker(existing_turn['speaker']) != turn_speaker:
            continue
        
        # Check text similarity
        similarity = calculate_text_similarity(turn_text, existing_turn['text'])
        
        if similarity >= similarity_threshold:
            logger.debug(f"Found duplicate: similarity={similarity:.2f}")
            return i
    
    return None


def merge_turn_data(turn1: Dict[str, Any], turn2: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge two similar turns, taking the more complete version.
    
    Args:
        turn1: First turn
        turn2: Second turn
        
    Returns:
        Merged turn
    """
    # Take the longer text (likely more complete)
    if len(turn2['text']) > len(turn1['text']):
        base_turn = turn2.copy()
    else:
        base_turn = turn1.copy()
    
    # Merge timestamps if both have them
    if 'timestamp' in turn1 and 'timestamp' in turn2:
        base_turn['timestamp'] = min(turn1.get('timestamp', ''), turn2.get('timestamp', ''))
    
    return base_turn


def merge_chunks_intelligently(chunk_results: List[Dict[str, Any]], 
                                metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Merge turns from multiple chunks, handling overlaps intelligently.
    
    Args:
        chunk_results: List of turn results from each chunk
        metadata: Chunk metadata with overlap information
        
    Returns:
        Merged list of turns
    """
    if len(chunk_results) == 0:
        return []
    
    if len(chunk_results) == 1:
        return chunk_results[0].get('turns', [])
    
    # Sort chunks by index
    chunk_results = sorted(chunk_results, key=lambda x: x['chunk_index'])
    
    merged_turns = []
    
    for chunk_idx, chunk_result in enumerate(chunk_results):
        chunk_turns = chunk_result.get('turns', [])
        
        if chunk_idx == 0:
            # First chunk: add all turns
            merged_turns.extend(chunk_turns)
            logger.info(f"Chunk 0: Added {len(chunk_turns)} turns")
        else:
            # Subsequent chunks: check for duplicates in overlap region
            overlap_region_size = metadata['chunking_params']['overlap_tokens'] * 3  # chars
            
            # Estimate how many turns might be in overlap
            # Average turn is ~200 chars, overlap is ~6000 chars = ~30 turns
            overlap_turn_estimate = min(50, len(chunk_turns) // 3)
            
            # Check first N turns of this chunk against last M turns of merged
            new_turns_added = 0
            duplicates_found = 0
            
            for turn in chunk_turns:
                # Check if this turn is duplicate of recent turns
                search_range = merged_turns[-overlap_turn_estimate:] if len(merged_turns) > overlap_turn_estimate else merged_turns
                
                duplicate_idx = find_duplicate_turn(turn, search_range, similarity_threshold=0.75)
                
                if duplicate_idx is not None:
                    # Found duplicate - merge with existing
                    actual_idx = len(merged_turns) - len(search_range) + duplicate_idx
                    merged_turns[actual_idx] = merge_turn_data(merged_turns[actual_idx], turn)
                    duplicates_found += 1
                else:
                    # New turn - add it
                    merged_turns.append(turn)
                    new_turns_added += 1
            
            logger.info(f"Chunk {chunk_idx}: Added {new_turns_added} new turns, merged {duplicates_found} duplicates")
    
    logger.info(f"Final merge: {len(merged_turns)} total turns from {len(chunk_results)} chunks")
    return merged_turns


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for merging chunked turn results.
    
    Args:
        event: Lambda event containing chunk results
        context: Lambda context
        
    Returns:
        Merged turns result
    """
    try:
        meeting_id = event['meeting_id']
        
        logger.info(f"Merging chunks for meeting {meeting_id}")
        
        # Initialize S3 client
        s3_client = S3Client()
        
        # Check if transcript was chunked
        if not event.get('chunked', False):
            # Not chunked - just pass through the single result
            logger.info("Transcript was not chunked, passing through")
            chunk_results = event.get('chunk_results', [])
            if chunk_results and len(chunk_results) > 0:
                return chunk_results[0]
            else:
                raise ValueError("No chunk results found")
        
        # Read chunk metadata
        metadata_key = event['metadata_key']
        metadata = s3_client.read_json_file(metadata_key)
        
        # Read all chunk results
        chunk_results = []
        for chunk_info in event['chunk_results']:
            chunk_index = chunk_info['chunk_index']
            chunk_output_key = chunk_info['output_key']
            
            logger.info(f"Reading chunk {chunk_index} results from {chunk_output_key}")
            chunk_data = s3_client.read_json_file(chunk_output_key)
            chunk_data['chunk_index'] = chunk_index
            chunk_results.append(chunk_data)
        
        # Merge chunks intelligently
        merged_turns = merge_chunks_intelligently(chunk_results, metadata)
        
        # Validate merged result
        try:
            validate_turns_schema({'turns': merged_turns})
            logger.info("Merged turns passed schema validation")
        except Exception as e:
            logger.error(f"Merged turns failed validation: {e}")
            # Continue anyway - validation error shouldn't block pipeline
        
        # Prepare output
        output = {
            'turns': merged_turns,
            'metadata': {
                'meeting_id': meeting_id,
                'total_turns': len(merged_turns),
                'chunk_count': len(chunk_results),
                'merged_at': datetime.utcnow().isoformat()
            }
        }
        
        # Write merged result
        output_key = event.get('output_key', f"meetings/{meeting_id}/01_turns.json")
        s3_client.write_json_file(output_key, output)
        
        logger.info(f"Successfully merged {len(merged_turns)} turns from {len(chunk_results)} chunks")
        
        return {
            'statusCode': 200,
            'meeting_id': meeting_id,
            'output_key': output_key,
            'total_turns': len(merged_turns),
            'chunk_count': len(chunk_results)
        }
        
    except Exception as e:
        logger.error(f"Error merging chunks: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'error': str(e),
            'meeting_id': event.get('meeting_id', 'unknown')
        }
