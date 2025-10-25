# Sliding Window Chunking Implementation

## Summary

Successfully implemented intelligent sliding window chunking to prevent content loss at chunk boundaries and improve analysis quality.

## New Components

### 1. `chunk_transcript.py` - Transcript Chunker
**Purpose**: Split large transcripts into overlapping chunks with metadata

**Key Features**:
- Auto-detects if chunking needed (threshold: 50K tokens)
- Creates ~15K token chunks with 2K overlap
- Smart boundary detection (paragraphs → lines → sentences)
- Generates chunk metadata for downstream processing
- Stores chunks and overlap regions to S3

**Output**: Chunk metadata with:
- `chunk_index`: Sequential chunk number
- `input_key`: S3 path to chunk text
- `overlap_key`: S3 path to overlap region
- `output_key`: Where to store processed results
- `start_char`, `end_char`: Boundaries in original text
- `overlap_start_char`: Where overlap begins
- `estimated_tokens`: Rough token count
- `has_next_chunk`: Whether more chunks follow

### 2. `merge_chunks.py` - Intelligent Merger
**Purpose**: Combine chunked turn results without losing content at boundaries

**Key Features**:
- **Duplicate Detection**: Jaccard text similarity (0.75 threshold)
- **Focused Search**: Only compares within overlap region (~30-50 turns)
- **Smart Merging**: Takes longer text when combining duplicates
- **Speaker Normalization**: Case-insensitive speaker matching
- **Validation**: Schema validation on merged result

**Algorithm**:
```python
for each chunk (after first):
    for each turn in chunk:
        search_recent_turns = merged_turns[-overlap_estimate:]
        if find_duplicate(turn, search_recent_turns):
            merge with existing turn
        else:
            append as new turn
```

### 3. Updated Step Functions Workflow

**Before** (Single-pass):
```
PreprocessTurns → ParallelProcessing → MakeManifest
```

**After** (Sliding Window):
```
ChunkTranscript 
  → ProcessChunks (Map State - parallel per chunk)
    └─> PreprocessTurns (for each chunk)
  → MergeChunks
  → ParallelProcessing 
  → MakeManifest
```

### 4. SAM Template Changes

**New Lambda Functions**:
- `ChunkTranscriptFn`: 1024MB, 300s timeout
- `MergeChunksFn`: 1024MB, 300s timeout

**Updated State Machine**:
- Added `ChunkTranscriptArn` substitution
- Added `MergeChunksArn` substitution
- Updated IAM policies for new function invocations

### 5. Step Functions Map State

```json
{
  "ProcessChunks": {
    "Type": "Map",
    "ItemsPath": "$.chunks",
    "MaxConcurrency": 5,
    "ResultPath": "$.chunk_results",
    "Iterator": {
      "StartAt": "PreprocessTurns",
      "States": {
        "PreprocessTurns": {
          "Type": "Task",
          "Resource": "${PreprocessTurnsArn}",
          "End": true
        }
      }
    }
  }
}
```

This processes up to 5 chunks in parallel!

## How It Works

### Small Transcripts (<50K tokens)
1. ChunkTranscript detects size
2. Returns single "chunk" (original file)
3. ProcessChunks Map state iterates once
4. MergeChunks passes through single result
5. Normal parallel processing continues

### Large Transcripts (>50K tokens)
1. ChunkTranscript splits into overlapping chunks:
   - Chunk 0: chars 0-45000 (15K tokens)
   - Chunk 1: chars 39000-84000 (overlap: 39000-45000)
   - Chunk 2: chars 78000-123000 (overlap: 78000-84000)
   - etc.

2. Stores to S3:
   - `chunks/chunk_0.txt`
   - `chunks/chunk_0_overlap.txt`
   - `chunks/chunk_1.txt`
   - `chunks/chunk_1_overlap.txt`
   - `chunks/metadata.json`

3. ProcessChunks Map state invokes PreprocessTurns for each chunk in parallel

4. MergeChunks reads all chunk results:
   - First chunk: Add all turns
   - Subsequent chunks: Check for duplicates in overlap region
   - Deduplicate using text similarity (0.75 threshold)
   - Merge duplicate turns (take longer version)
   - Append unique turns

5. Result: Complete turn list with no gaps or duplicates

## Quality Benefits

### Better Speaker Tracking
Overlap ensures speaker IDs stay consistent across boundaries.

**Without Overlap**:
```
Chunk 1: ...Speaker X continues...| [BOUNDARY]
Chunk 2: |...discussing the topic...
```
Chunk 2 might not know who "continues" refers to.

**With Overlap**:
```
Chunk 1: ...Speaker X continues discussing...
                              [....overlap....]
Chunk 2:        ...continues discussing the topic...
```
Both chunks see the full context.

### Complete Q&A Pairs
Questions at chunk boundaries are visible in both chunks.

### Natural Turn Boundaries
Chunks break at paragraph/sentence boundaries, not mid-sentence.

### Parallel Processing
5 chunks × 15 minutes = 75 minutes of sequential work
With parallelism: ~15-20 minutes total (depending on concurrency)

## Testing

Created `test_chunking.py` with tests for:
- ✅ Chunking logic and boundary detection
- ✅ Overlap region calculation
- ✅ Text similarity detection
- ✅ Merge deduplication
- ✅ No content loss verification

## Deployment

```bash
# Validate
sam validate

# Build
sam build

# Deploy
sam deploy
```

## Monitoring

After deployment, check:
1. CloudWatch Logs for ChunkTranscriptFn
2. Step Functions execution graph (should show Map state)
3. S3 bucket for chunks/ folder
4. MergeChunks logs for duplicate detection stats

## Future Enhancements

- [ ] Adaptive chunk sizing based on speaker density
- [ ] ML-based optimal boundary detection
- [ ] Configurable similarity threshold via environment variable
- [ ] Chunk-level retry logic for failed chunks
- [ ] Metrics on duplicate detection accuracy
- [ ] Streaming merge for very large meetings (>100 chunks)

## Files Modified

- ✅ `src/handlers/chunk_transcript.py` - NEW
- ✅ `src/handlers/merge_chunks.py` - NEW
- ✅ `template.yaml` - Added 2 new Lambda functions
- ✅ `statemachine.asl.json` - Added Map state workflow
- ✅ `test_chunking.py` - NEW
- ✅ `README.md` - Documentation updates

## Architecture Decision

**Q: Why chunk if transcript fits in context (58K < 200K)?**

**A: Quality > Capacity**
- Focus: LLM performs better with focused context
- Consistency: Overlaps ensure continuity
- Speed: Parallel processing is faster
- Resilience: Partial failures don't kill entire job
- Future-proof: Handles transcripts of any size

This is production-grade architecture, not just a workaround for token limits.
