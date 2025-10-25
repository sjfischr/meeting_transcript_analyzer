"""
Count tokens in a transcript file using tiktoken (OpenAI's tokenizer).
Claude uses a similar tokenization method, so this gives a good estimate.
"""

import sys
import os

try:
    import tiktoken
except ImportError:
    print("Installing tiktoken...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "tiktoken"])
    import tiktoken


def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """
    Count tokens in text using tiktoken.
    
    Args:
        text: Text to count tokens for
        model: Encoding to use (cl100k_base is used by GPT-4 and similar to Claude)
    
    Returns:
        Number of tokens
    """
    encoding = tiktoken.get_encoding(model)
    tokens = encoding.encode(text)
    return len(tokens)


def analyze_transcript(file_path: str):
    """Analyze transcript file and print token statistics."""
    
    # Read the file
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Get file stats
    file_size = os.path.getsize(file_path)
    char_count = len(content)
    line_count = content.count('\n') + 1
    word_count = len(content.split())
    
    # Count tokens
    token_count = count_tokens(content)
    
    # Calculate estimates
    chars_per_token = char_count / token_count if token_count > 0 else 0
    
    # Print results
    print("=" * 70)
    print(f"TRANSCRIPT ANALYSIS: {os.path.basename(file_path)}")
    print("=" * 70)
    print(f"\nFile Statistics:")
    print(f"  File Size:       {file_size:,} bytes ({file_size / (1024*1024):.2f} MB)")
    print(f"  Characters:      {char_count:,}")
    print(f"  Lines:           {line_count:,}")
    print(f"  Words:           {word_count:,}")
    print(f"\nToken Analysis:")
    print(f"  Total Tokens:    {token_count:,}")
    print(f"  Chars/Token:     {chars_per_token:.2f}")
    print(f"\nClaude Context Limits:")
    print(f"  Input Limit:     200,000 tokens")
    print(f"  Output Limit:    200,000 tokens (for Sonnet 4.5)")
    print(f"\nTranscript Usage:")
    print(f"  Input Used:      {(token_count / 200000) * 100:.1f}% of context window")
    
    if token_count > 200000:
        print(f"  ⚠️  WARNING: Transcript exceeds Claude's 200K token limit!")
        print(f"  ⚠️  Needs chunking: ~{(token_count // 150000) + 1} chunks recommended")
    elif token_count > 150000:
        print(f"  ⚠️  WARNING: Large transcript - may need chunking for safety margin")
    else:
        print(f"  ✅ Transcript fits within context window")
    
    # Estimate output needs
    # Assuming ~1 turn per 50 tokens of input as a rough estimate
    estimated_turns = token_count // 50
    # JSON overhead: ~100 chars per turn structure = ~25 tokens per turn
    estimated_output_tokens = estimated_turns * 25
    
    print(f"\nEstimated Output:")
    print(f"  Estimated Turns: ~{estimated_turns:,}")
    print(f"  Output Tokens:   ~{estimated_output_tokens:,}")
    print(f"  Output Used:     {(estimated_output_tokens / 200000) * 100:.1f}% of output limit")
    
    if estimated_output_tokens > 100000:
        print(f"  ⚠️  Output may be very large - consider chunking")
    
    print("=" * 70)


if __name__ == "__main__":
    # Get transcript file path
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        # Use the default transcript file
        file_path = "GMT20251021-224835_Recording_3840x2160.txt"
    
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        print(f"\nUsage: python count_tokens.py [transcript_file.txt]")
        sys.exit(1)
    
    analyze_transcript(file_path)
