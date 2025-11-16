# Meeting Transcript Analysis Pipeline

AWS SAM application for processing meeting transcripts using Step Functions, Lambda, and Amazon Bedrock.

## Overview

This pipeline converts raw meeting transcripts into structured outputs using **intelligent sliding window chunking** for optimal quality:

### Output Files
1. **01_turns.json** - Atomic turns with speaker identification and timestamps
2. **02_qa_pairs.json** - Grouped Q&A exchanges and discussions  
3. **03_minutes.json** - Formal meeting minutes with action items
4. **04_summaries.json** - Executive and detailed summaries
5. **05_events.ics** - Calendar events extracted from meeting content
6. **06_manifest.json** - Processing metadata and quality metrics
7. **meeting_report.docx** *(optional)* - Combined summary + minutes export produced locally with `scripts/export_docx.py` (can now embed QA exchanges)

### Sliding Window Chunking 🎯

For transcripts >50K tokens, the pipeline automatically:
- **Splits** transcript into ~15K token overlapping chunks (2K overlap)
- **Processes** chunks in parallel via Step Functions Map state
- **Merges** results intelligently, deduplicating overlaps
- **Benefits**: Better speaker tracking, turn boundaries, Q&A coherence, parallel processing

```
Chunk 1: [===============]
                    [===============] Chunk 2
                              [===============] Chunk 3
         └── 2K overlap ──┘
```

## Architecture

- **AWS SAM** - Infrastructure as Code
- **Step Functions** - Orchestration workflow
- **Lambda** - Processing functions (Python 3.12)
- **Amazon Bedrock** - LLM inference using Claude Haiku 4.5 (Sonnet available via override)
- **S3** - Storage for inputs and outputs
- **EventBridge** - Automatic trigger on file upload

### Event Flow

1. **Upload** - Transcript (.txt) uploaded to S3 bucket
2. **EventBridge** - Detects S3 "Object Created" event
3. **Trigger Lambda** - Extracts meeting info and starts Step Functions
4. **Chunking** - Splits large transcripts into overlapping segments
5. **Parallel Processing** - Map state processes chunks simultaneously
6. **Merge** - Intelligently combines chunks, deduplicating overlaps
7. **Analysis Pipeline** - Four parallel processing branches (Q&A, Minutes, Summaries, Calendar)
8. **Manifest** - Collects metadata and creates final manifest
9. **Output** - All results saved to S3 in meeting-specific folder

### Processing Steps

```
S3 Upload → EventBridge → Trigger Lambda → Step Functions:
  ┌─────────────────────────────────────────────────────────────┐
  │ 1. ChunkTranscript (auto-splits if >50K tokens)             │
  │    └─> Creates overlapping chunks with metadata             │
  │                                                              │
  │ 2. ProcessChunks (Map State - parallel)                     │
  │    ├─> PreprocessTurns (Chunk 1) ─┐                         │
  │    ├─> PreprocessTurns (Chunk 2) ─┤                         │
  │    ├─> PreprocessTurns (Chunk 3) ─┼─> All chunks in ||      │
  │    └─> PreprocessTurns (Chunk N) ─┘                         │
  │                                                              │
  │ 3. MergeChunks                                               │
  │    └─> Intelligent deduplication of overlaps                │
  │                                                              │
  │ 4. ParallelProcessing (4 branches)                           │
  │    ├─> GroupQA                                               │
  │    ├─> MinutesActions                                        │
  │    ├─> Summarize                                             │
  │    └─> MakeIcs                                               │
  │                                                              │
  │ 5. MakeManifest                                              │
  │    └─> Collects all outputs and metadata                    │
  └─────────────────────────────────────────────────────────────┘
```

## Project Structure

```
├── template.yaml              # SAM template
├── statemachine.asl.json      # Step Functions definition
├── prompts/                   # LLM prompt templates
│   ├── 01_turns.md
│   ├── 02_qa_grouper.md  
│   ├── 03_minutes_actions.md
│   ├── 04_summaries.md
│   ├── 05_ics.md
│   └── 06_manifest.md
├── src/
│   ├── common/               # Shared utilities
│   │   ├── bedrock_client.py
│   │   ├── s3io.py
│   │   └── json_utils.py
│   ├── handlers/             # Lambda functions
│   │   ├── chunk_transcript.py    # 🆕 Split into overlapping chunks
│   │   ├── merge_chunks.py        # 🆕 Intelligent chunk merging
│   │   ├── preprocess_turns.py
│   │   ├── group_qa.py
│   │   ├── minutes_actions.py
│   │   ├── summarize.py
│   │   ├── make_ics.py
│   │   ├── make_manifest.py
│   │   └── trigger_pipeline.py    # EventBridge handler
│   └── models/               # Type definitions
│       ├── types.py
│       └── schemas.py
└── tests/                    # Unit tests
    ├── test_smoke.py
    └── test_chunking.py      # 🆕 Chunking & merge tests
```

## Environment Variables

- `BUCKET` - S3 bucket for storing files
- `REGION` - AWS region (default: us-east-1)  
- `TIME_ZONE` - Meeting timezone (default: America/New_York)
- `INFERENCE_PROFILE_ARN` - Bedrock inference profile ARN (defaults to Claude Haiku 4.5 when unset)
- `SEGMENT_ANALYSIS_MODEL_ID` / `BEDROCK_MODEL_ID` - Override the default Claude Haiku 4.5 model ID for local or Lambda runs
- `MOCK_BEDROCK` - When truthy, enables deterministic offline analysis instead of calling Bedrock
- `SKIP_CALENDAR` - Optional flag (`true`/`false`) to bypass calendar generation in the pipeline reprocessor

## Setup & Deployment

### Prerequisites
- AWS CLI configured
- SAM CLI installed  
- Python 3.12
- S3 bucket with EventBridge notifications enabled

### Enable EventBridge on S3 Bucket (One-Time Setup)

✅ **You already did this!** But for reference:

```bash
aws s3api put-bucket-notification-configuration \
  --bucket your-meeting-bucket \
  --notification-configuration '{"EventBridgeConfiguration": {}}'
```

### Build & Deploy

```bash
# Build the application
sam build

# Deploy (first time - will prompt for confirmations)
sam deploy --guided

# Subsequent deployments
sam deploy
```

### Local Testing

```bash
# Validate imports and project structure
python test_local.py

# Run unit tests
python -m pytest tests/
```

### Local Utilities

```bash
# Re-run specific pipeline stages locally via CLI
python scripts/pipeline_cli.py reprocess \
  --meeting-id club-2025-10-22 \
  --skip-calendar

# Export DOCX combining summaries + minutes
python scripts/export_docx.py \
  outputs/04_summaries.json \
  outputs/03_minutes.json \
  meeting_report.docx \
  --qa-json outputs/02_qa_pairs.json

# Analyze a transcript locally (mock mode shown; see below for details)
python scripts/run_segment_analysis_local.py \
  data/segment_analysis_output/November_mtg_transcribe.txt \
  --mock-llm
```

The CLI uses the same IAM credentials as your AWS CLI profile. It supports targeted retries (minutes-only, summaries-only), per-stage backoff configuration, and a `--skip-calendar` option for faster dry runs. The DOCX exporter relies on `python-docx`; install dependencies with `pip install -r requirements.txt` before running.

### Local Transcript Analysis

`scripts/run_segment_analysis_local.py` now supports both raw text transcripts and full AWS Transcribe JSON exports:

- **Transcribe-aware turn parsing** – The loader consumes `results.items` and aligns tokens with `speaker_labels.segments`, yielding accurate speaker continuity and timestamps straight from the transcription service.
- **Mock mode** – Supply `--mock-llm` (or set `MOCK_BEDROCK=1`) to generate deterministic heuristic summaries without invoking Bedrock. This is ideal for CI, credential-free environments, or quick regression checks.
- **Bedrock execution** – When run without `--mock-llm`, the script calls Bedrock using the default Claude Haiku 4.5 profile. Provide `INFERENCE_PROFILE_ARN` or `SEGMENT_ANALYSIS_MODEL_ID` to target a different model.
- **Artifacts** – The command writes the same suite of JSON/ICS outputs used by the Step Functions pipeline into `segment_analysis_output/` for easy inspection. These paths are ignored by Git.

Examples:

```bash
# Offline heuristic run
python scripts/run_segment_analysis_local.py data/November_mtg.txt --mock-llm

# Full run against an AWS Transcribe export
python scripts/run_segment_analysis_local.py data/segment_analysis_output/November_mtg_transcribe.txt
```

### Usage

### Automatic Processing (Recommended) 🚀

Simply upload a .txt transcript file to S3 - the pipeline starts automatically!

```bash
# Upload anywhere in the bucket - auto-organizes by filename
aws s3 cp meeting_transcript.txt s3://your-meeting-bucket/GMT20251022-club-meeting.txt

# Or organize manually by date
aws s3 cp transcript.txt s3://your-meeting-bucket/meetings/2025-10-22/transcript.txt
```

**What happens next:**
1. EventBridge detects the upload
2. `TriggerPipelineFn` extracts meeting info from path/filename
3. Step Functions pipeline starts automatically
4. All outputs saved to `meetings/{meeting-id}/` folder

### Manual Trigger (If Needed)

Start Step Functions execution manually:

```bash
STATE_MACHINE_ARN=$(aws cloudformation describe-stacks \
  --stack-name meeting-pipeline \
  --query "Stacks[0].Outputs[?OutputKey=='MeetingPipelineStateMachineArn'].OutputValue" \
  --output text)

aws stepfunctions start-execution \
  --state-machine-arn $STATE_MACHINE_ARN \
  --input '{
    "meeting_id": "club-2025-10-22",
    "input_key": "GMT20251021-224835_Recording.txt",
    "output_key": "meetings/club-2025-10-22/"
  }'
```

### Monitor Execution

```bash
# List recent executions
aws stepfunctions list-executions --state-machine-arn $STATE_MACHINE_ARN

# Tail trigger function logs
sam logs --stack-name meeting-pipeline --name TriggerPipelineFn --tail

# View specific Lambda logs
aws logs tail /aws/lambda/meeting-pipeline-PreprocessTurnsFn --follow
```

### Retrieve Results

```bash
# List all outputs for a meeting
aws s3 ls s3://your-meeting-bucket/meetings/club-2025-10-22/

# Download specific output
aws s3 cp s3://your-meeting-bucket/meetings/club-2025-10-22/manifest.json .
```

## Development

### Chunking Strategy

**Why Chunk?** Even when transcripts fit in Claude's 200K context window, chunking provides:
- ✅ **Better Quality**: Focused analysis per chunk vs. overwhelming context
- ✅ **Speaker Consistency**: Overlap regions ensure continuous speaker tracking
- ✅ **Turn Boundaries**: Natural breaks prevent cutting mid-conversation
- ✅ **Parallel Processing**: Multiple chunks process simultaneously (faster)
- ✅ **Resilience**: One chunk failure doesn't kill entire pipeline

**Chunking Parameters** (in `chunk_transcript.py`):
- `chunk_size_tokens`: 15,000 (target size per chunk)
- `overlap_tokens`: 2,000 (overlap between adjacent chunks)
- `threshold`: 50,000 tokens (auto-chunk if transcript exceeds)

**Smart Boundary Detection**: 
Chunks break at natural points (paragraphs → lines → sentences) rather than mid-word.

**Deduplication Logic** (in `merge_chunks.py`):
- Compares turns via Jaccard similarity on normalized text
- Threshold: 0.75 similarity = duplicate
- Takes longer text when merging duplicates
- Searches only within overlap region (efficient)

### Adding New Handlers
1. Create handler in `src/handlers/`
2. Add to `template.yaml` 
3. Update `statemachine.asl.json`
4. Add corresponding prompt in `prompts/`

### Type Safety
All functions use Python type hints with TypedDict definitions in `src/models/types.py`.

### Validation
JSON schema validation is performed using definitions in `src/models/schemas.py`.

## Monitoring

- CloudWatch Logs for Lambda functions
- Step Functions execution history
- S3 bucket metrics for storage usage

## Security

- Least-privilege IAM roles
- VPC endpoints for AWS service communication
- Encryption at rest for S3 storage