"""
Lambda handler for chunking large transcripts with sliding window overlap.

This function splits transcripts into overlapping chunks, processes each chunk
separately, then intelligently merges the results to prevent missing content
at chunk boundaries.
"""

import json
import os
import logging
from typing import Dict, Any, List, Tuple
from datetime import datetime

from common.s3io import S3Client
from models.types import LambdaEvent

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def count_tokens_estimate(text: str) -> int:
    """
    Estimate token count (rough approximation: ~2.5 chars per token).
    
    Args:
        text: Text to count
        
    Returns:
        Estimated token count
    """
    return len(text) // 3  # Conservative estimate


def find_natural_break(text: str, target_pos: int, search_range: int = 500) -> int:
    """
    Find a natural break point (paragraph, sentence) near target position.
    
    Args:
        text: Text to search
        target_pos: Ideal position for break
        search_range: How far to search for natural break
        
    Returns:
        Position of natural break
    """
    # Ensure we don't go out of bounds
    start = max(0, target_pos - search_range)
    end = min(len(text), target_pos + search_range)
    
    # Search backwards first for paragraph break (more natural)
    for i in range(target_pos, start, -1):
        if i + 1 < len(text) and text[i:i+2] == '\n\n':
            return i + 2
    
    # Search forwards for paragraph break
    for i in range(target_pos, end - 1):
        if text[i:i+2] == '\n\n':
            return i + 2
    
    # Search backwards for line break
    for i in range(target_pos, start, -1):
        if text[i] == '\n':
            return i + 1
    
    # Search forwards for line break
    for i in range(target_pos, end):
        if text[i] == '\n':
            return i + 1
    
    # Fall back to target position
    return target_pos


def create_overlapping_chunks(
    text: str, 
    chunk_size_tokens: int = 15000,
    overlap_tokens: int = 2000
) -> List[Dict[str, Any]]:
    """
    Split text into overlapping chunks with metadata.
    
    Args:
        text: Full transcript text
        chunk_size_tokens: Target size for each chunk
        overlap_tokens: Overlap between chunks
        
    Returns:
        List of chunk dictionaries with metadata
    """
    chunks = []
    total_length = len(text)
    
    # Convert token counts to character positions (rough estimate: 1 token ≈ 3 chars)
    chunk_size_chars = chunk_size_tokens * 3
    overlap_chars = overlap_tokens * 3
    stride = chunk_size_chars - overlap_chars  # How far to advance each chunk
    
    current_pos = 0
    chunk_index = 0
    
    logger.info(f"Chunking {total_length:,} chars (est. {total_length // 3:,} tokens)")
    logger.info(f"Chunk size: {chunk_size_chars:,} chars, Overlap: {overlap_chars:,} chars")
    
    while current_pos < total_length:
        chunk_start = current_pos
        chunk_end_target = min(current_pos + chunk_size_chars, total_length)
        
        # Find natural break point for chunk end (only if not at end of text)
        if chunk_end_target < total_length:
            chunk_end = find_natural_break(text, chunk_end_target, search_range=500)
        else:
            chunk_end = total_length
        
        # Extract chunk text (single slice operation)
        chunk_text = text[chunk_start:chunk_end]
        
        # Calculate overlap for next chunk
        has_next = chunk_end < total_length
        if has_next:
            overlap_start = max(chunk_start, chunk_end - overlap_chars)
            overlap_text = text[overlap_start:chunk_end]
        else:
            overlap_start = chunk_end
            overlap_text = ""
        
        # Store chunk metadata
        chunks.append({
            'chunk_index': chunk_index,
            'chunk_text': chunk_text,
            'start_char': chunk_start,
            'end_char': chunk_end,
            'overlap_start_char': overlap_start,
            'overlap_text': overlap_text,
            'estimated_tokens': count_tokens_estimate(chunk_text),
            'has_next_chunk': has_next
        })
        
        logger.info(f"Chunk {chunk_index}: chars {chunk_start:,}-{chunk_end:,} ({len(chunk_text):,} chars)")
        
        chunk_index += 1
        
        # Move to next chunk start (advance by stride, then find natural break)
        if has_next:
            next_start_target = chunk_start + stride
            if next_start_target < total_length:
                current_pos = find_natural_break(text, next_start_target, search_range=500)
            else:
                current_pos = total_length
        else:
            break
    
    logger.info(f"Created {len(chunks)} chunks from {total_length:,} character transcript")
    return chunks


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for chunking transcripts with sliding window.
    
    Args:
        event: Lambda event containing meeting_id, input_key
        context: Lambda context
        
    Returns:
        Response with chunk information for downstream processing
    """
    start_time = datetime.utcnow()
    
    try:
        # Parse event
        meeting_id = event['meeting_id']
        input_key = event['input_key']
        output_key_base = event.get('output_key', f"meetings/{meeting_id}/")
        
        logger.info(f"Chunking transcript for meeting {meeting_id}")
        logger.info(f"Input: {input_key}")
        
        # Initialize S3 client
        s3_client = S3Client()
        
        # Read full transcript
        logger.info("Reading transcript from S3...")
        transcript_text = s3_client.read_text_file(input_key)
        logger.info(f"Read transcript: {len(transcript_text):,} characters")
        
        # Determine if chunking is needed (fast check)
        estimated_tokens = count_tokens_estimate(transcript_text)
        needs_chunking = estimated_tokens > 50000  # Chunk if > 50K tokens
        
        logger.info(f"Estimated tokens: {estimated_tokens:,}, Needs chunking: {needs_chunking}")
        
        if not needs_chunking:
            # Early return for small transcripts (fast path)
            logger.info(f"Transcript is small, no chunking needed")
            result = {
                'statusCode': 200,
                'meeting_id': meeting_id,
                'input_key': input_key,
                'output_key': output_key_base,
                'chunked': False,
                'chunk_count': 1,
                'chunks': [{
                    'chunk_index': 0,
                    'input_key': input_key,
                    'output_key': f"{output_key_base}chunk_0_turns.json"
                }]
            }
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            logger.info(f"Completed in {elapsed:.2f}s (no chunking)")
            return result
        
        # Create overlapping chunks
        chunks = create_overlapping_chunks(
            transcript_text,
            chunk_size_tokens=15000,
            overlap_tokens=2000
        )
        
        logger.info(f"Writing {len(chunks)} chunks to S3...")
        
        # Upload each chunk to S3 (batch metadata for single write)
        chunk_metadata = []
        for chunk in chunks:
            chunk_key = f"{output_key_base}chunks/chunk_{chunk['chunk_index']}.txt"
            
            # Write chunk text
            s3_client.write_text_file(chunk_key, chunk['chunk_text'])
            logger.info(f"Wrote chunk {chunk['chunk_index']} ({len(chunk['chunk_text']):,} chars)")
            
            # Only write overlap if exists (save S3 operations)
            overlap_key = None
            if chunk['overlap_text']:
                overlap_key = f"{output_key_base}chunks/chunk_{chunk['chunk_index']}_overlap.txt"
                s3_client.write_text_file(overlap_key, chunk['overlap_text'])
            
            chunk_metadata.append({
                'chunk_index': chunk['chunk_index'],
                'input_key': chunk_key,
                'overlap_key': overlap_key,
                'output_key': f"{output_key_base}chunk_{chunk['chunk_index']}_turns.json",
                'start_char': chunk['start_char'],
                'end_char': chunk['end_char'],
                'overlap_start_char': chunk['overlap_start_char'],
                'estimated_tokens': chunk['estimated_tokens'],
                'has_next_chunk': chunk['has_next_chunk']
            })
        
        # Write chunk metadata (single write at end)
        metadata_key = f"{output_key_base}chunks/metadata.json"
        s3_client.write_json_file(metadata_key, {
            'meeting_id': meeting_id,
            'original_input_key': input_key,
            'chunk_count': len(chunks),
            'total_chars': len(transcript_text),
            'estimated_total_tokens': estimated_tokens,
            'chunking_params': {
                'chunk_size_tokens': 15000,
                'overlap_tokens': 2000
            },
            'chunks': chunk_metadata,
            'created_at': datetime.utcnow().isoformat()
        })
        
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        logger.info(f"Successfully created {len(chunks)} chunks in {elapsed:.2f}s")
        
        return {
            'statusCode': 200,
            'meeting_id': meeting_id,
            'chunked': True,
            'chunk_count': len(chunks),
            'metadata_key': metadata_key,
            'chunks': chunk_metadata
        }
        
    except Exception as e:
        elapsed = (datetime.utcnow() - start_time).total_seconds()
        logger.error(f"Error chunking transcript after {elapsed:.2f}s: {e}", exc_info=True)
        return {
            'statusCode': 500,
            'error': str(e),
            'meeting_id': event.get('meeting_id', 'unknown')
        }
