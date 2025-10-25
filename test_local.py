"""
Local test script to validate the Lambda handlers can import correctly.

Run this before `sam build` to catch import errors early.
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    
    try:
        # Test common modules
        from common.bedrock_client import BedrockClient
        print("✓ bedrock_client imported")
        
        from common.s3io import S3Client
        print("✓ s3io imported")
        
        from common.json_utils import validate_turns_schema, sanitize_json_string
        print("✓ json_utils imported")
        
        # Test models
        from models.types import Turn, QAGroup, Minutes
        print("✓ models.types imported")
        
        from models.schemas import TURNS_SCHEMA, QA_PAIRS_SCHEMA
        print("✓ models.schemas imported")
        
        # Test handlers (just import, don't run)
        from handlers import preprocess_turns
        print("✓ preprocess_turns imported")
        
        from handlers import group_qa
        print("✓ group_qa imported")
        
        from handlers import minutes_actions
        print("✓ minutes_actions imported")
        
        from handlers import summarize
        print("✓ summarize imported")
        
        from handlers import make_ics
        print("✓ make_ics imported")
        
        from handlers import make_manifest
        print("✓ make_manifest imported")
        
        print("\n✅ All imports successful!")
        return True
        
    except ImportError as e:
        print(f"\n❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return False


def test_prompt_files():
    """Check that all prompt files exist."""
    print("\nChecking prompt files...")
    
    prompts_dir = os.path.join(os.path.dirname(__file__), 'prompts')
    expected_prompts = [
        '01_turns.md',
        '02_qa_grouper.md',
        '03_minutes_actions.md',
        '04_summaries.md',
        '05_ics.md',
        '06_manifest.md'
    ]
    
    all_exist = True
    for prompt in expected_prompts:
        path = os.path.join(prompts_dir, prompt)
        if os.path.exists(path):
            print(f"✓ {prompt} exists")
        else:
            print(f"✗ {prompt} missing")
            all_exist = False
    
    if all_exist:
        print("\n✅ All prompt files found!")
    else:
        print("\n⚠️  Some prompt files are missing")
    
    return all_exist


if __name__ == '__main__':
    import_success = test_imports()
    prompt_success = test_prompt_files()
    
    if import_success and prompt_success:
        print("\n🎉 Project is ready for testing!")
        print("\nNext steps:")
        print("1. sam build")
        print("2. sam deploy --guided")
        sys.exit(0)
    else:
        print("\n⚠️  Fix the issues above before deploying")
        sys.exit(1)
