<!-- Use this file to provide workspace-specific custom instructions to Copilot. For more details, visit https://code.visualstudio.com/docs/copilot/copilot-customization#_use-a-githubcopilotinstructionsmd-file -->

# GRiST Meeting Pipeline - Custom Instructions

This is an AWS SAM application for processing meeting transcripts using Step Functions, Lambda, and Amazon Bedrock.

## Project Context
- Python 3.12 Lambda functions
- AWS SAM for infrastructure
- Step Functions for orchestration
- Amazon Bedrock for LLM processing
- S3 for storage
- Clean modular architecture with typed Python

## Development Guidelines
- Use Python type hints throughout
- Keep functions focused and testable
- Follow AWS Lambda best practices
- Use least-privilege IAM policies
- Validate JSON schemas rigorously