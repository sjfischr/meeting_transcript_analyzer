"""
Test chunking and merging logic locally
"""

import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from handlers.chunk_transcript import create_overlapping_chunks, count_tokens_estimate
from handlers.merge_chunks import merge_chunks_intelligently, calculate_text_similarity


def test_chunking():
    """Test chunking with sample transcript"""
    print("=" * 80)
    print("TESTING CHUNKING LOGIC")
    print("=" * 80)
    
    # Read transcript
    transcript_path = Path(__file__).parent / "GMT20251021-224835_Recording_3840x2160.txt"
    with open(transcript_path, 'r', encoding='utf-8') as f:
        transcript = f.read()
    
    print(f"\nTranscript length: {len(transcript):,} characters")
    print(f"Estimated tokens: {count_tokens_estimate(transcript):,}")
    
    # Create chunks
    chunks = create_overlapping_chunks(
        transcript,
        chunk_size_tokens=15000,
        overlap_tokens=2000
    )
    
    print(f"\n✅ Created {len(chunks)} chunks")
    
    for i, chunk in enumerate(chunks):
        print(f"\nChunk {i}:")
        print(f"  - Characters: {chunk['end_char'] - chunk['start_char']:,}")
        print(f"  - Estimated tokens: {chunk['estimated_tokens']:,}")
        print(f"  - Has overlap: {bool(chunk['overlap_text'])}")
        if chunk['overlap_text']:
            print(f"  - Overlap chars: {len(chunk['overlap_text']):,}")
        print(f"  - Preview: {chunk['chunk_text'][:100]}...")
    
    # Test overlap detection
    print("\n" + "=" * 80)
    print("TESTING OVERLAP DETECTION")
    print("=" * 80)
    
    for i in range(len(chunks) - 1):
        current_chunk = chunks[i]
        next_chunk = chunks[i + 1]
        
        # Check if next chunk starts within current chunk's overlap region
        overlap_detected = next_chunk['start_char'] >= current_chunk['overlap_start_char']
        
        print(f"\nChunk {i} → Chunk {i+1}:")
        print(f"  - Current ends at: {current_chunk['end_char']:,}")
        print(f"  - Overlap starts at: {current_chunk['overlap_start_char']:,}")
        print(f"  - Next starts at: {next_chunk['start_char']:,}")
        print(f"  - Overlap detected: {overlap_detected}")
        
        if overlap_detected:
            overlap_size = current_chunk['end_char'] - next_chunk['start_char']
            print(f"  - Overlap size: {overlap_size:,} chars")


def test_similarity():
    """Test text similarity detection"""
    print("\n" + "=" * 80)
    print("TESTING SIMILARITY DETECTION")
    print("=" * 80)
    
    test_cases = [
        ("Hello world", "Hello world", 1.0),
        ("The quick brown fox", "The quick brown fox jumps", 0.8),
        ("Completely different", "Something else entirely", 0.0),
        ("John: Yes, I agree with that", "John: Yes, I agree with that.", 0.9),
    ]
    
    for text1, text2, expected_min in test_cases:
        similarity = calculate_text_similarity(text1, text2)
        passed = similarity >= expected_min
        status = "✅" if passed else "❌"
        print(f"\n{status} Similarity: {similarity:.3f} (expected >= {expected_min})")
        print(f"  Text 1: {text1}")
        print(f"  Text 2: {text2}")


def test_merge():
    """Test merge logic with sample data"""
    print("\n" + "=" * 80)
    print("TESTING MERGE LOGIC")
    print("=" * 80)
    
    # Simulate two chunks with overlapping content
    chunk1_turns = [
        {"idx": 0, "speaker": "Alice", "text": "Welcome everyone to the meeting"},
        {"idx": 1, "speaker": "Bob", "text": "Thanks Alice, glad to be here"},
        {"idx": 2, "speaker": "Alice", "text": "Let's start with the first topic"},  # Overlap starts
        {"idx": 3, "speaker": "Charlie", "text": "I have a question about that"},
    ]
    
    chunk2_turns = [
        {"idx": 0, "speaker": "Alice", "text": "Let's start with the first topic"},  # Duplicate
        {"idx": 1, "speaker": "Charlie", "text": "I have a question about that"},  # Duplicate
        {"idx": 2, "speaker": "Alice", "text": "Sure, go ahead Charlie"},  # New
        {"idx": 3, "speaker": "Charlie", "text": "What's the timeline?"},  # New
    ]
    
    chunk_results = [
        {"chunk_index": 0, "turns": chunk1_turns},
        {"chunk_index": 1, "turns": chunk2_turns}
    ]
    
    metadata = {
        "chunking_params": {
            "chunk_size_tokens": 15000,
            "overlap_tokens": 2000
        }
    }
    
    merged = merge_chunks_intelligently(chunk_results, metadata)
    
    print(f"\nChunk 1: {len(chunk1_turns)} turns")
    print(f"Chunk 2: {len(chunk2_turns)} turns")
    print(f"Merged: {len(merged)} turns")
    print(f"Expected: {len(chunk1_turns) + len(chunk2_turns) - 2} turns (2 duplicates)")
    
    print("\nMerged turns:")
    for i, turn in enumerate(merged):
        print(f"  {i}: {turn['speaker']}: {turn['text']}")
    
    # Verify no duplicates
    unique_texts = set()
    duplicates = 0
    for turn in merged:
        text_key = f"{turn['speaker']}:{turn['text']}"
        if text_key in unique_texts:
            duplicates += 1
        unique_texts.add(text_key)
    
    if duplicates == 0:
        print(f"\n✅ No duplicates found in merged result")
    else:
        print(f"\n❌ Found {duplicates} duplicates in merged result")


if __name__ == "__main__":
    test_chunking()
    test_similarity()
    test_merge()
    print("\n" + "=" * 80)
    print("ALL TESTS COMPLETE")
    print("=" * 80)
