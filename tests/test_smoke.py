"""
Smoke tests for GRiST meeting pipeline.

Basic tests to ensure the project structure is correct and
imports work as expected.
"""

import unittest
import json
import os
import sys
from unittest.mock import Mock, patch

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Import modules to test
from common.json_utils import validate_json_structure, sanitize_json_string
from models.types import Turn, TurnsOutput


class TestProjectStructure(unittest.TestCase):
    """Test basic project structure and imports."""
    
    def test_imports_work(self):
        """Test that all main modules can be imported."""
        try:
            from common.bedrock_client import BedrockClient
            from common.s3io import S3Client
            from common.json_utils import validate_turns_schema
            from models.schemas import TURNS_SCHEMA
            from models.types import Turn
        except ImportError as e:
            self.fail(f"Failed to import modules: {e}")
    
    def test_json_validation(self):
        """Test JSON validation utilities."""
        # Test valid structure
        data = {"meeting_id": "test", "turns": []}
        errors = validate_json_structure(data, ["meeting_id", "turns"])
        self.assertEqual(len(errors), 0)
        
        # Test missing field
        data = {"meeting_id": "test"}
        errors = validate_json_structure(data, ["meeting_id", "turns"])
        self.assertEqual(len(errors), 1)
        self.assertIn("turns", errors[0])
    
    def test_json_sanitization(self):
        """Test JSON string sanitization."""
        dirty_text = "  Hello\nWorld\r\n  "
        clean_text = sanitize_json_string(dirty_text)
        self.assertEqual(clean_text, "Hello World")
    
    def test_type_definitions(self):
        """Test that type definitions are valid."""
        # This is mainly a compile-time check
        turn: Turn = {
            "idx": 0,
            "start_ts": "00:01:30",
            "end_ts": "00:01:45", 
            "speaker": "Alice",
            "type": "question",
            "question_likelihood": 0.8,
            "text": "What time is the meeting?"
        }
        
        self.assertEqual(turn["idx"], 0)
        self.assertEqual(turn["type"], "question")


class TestSchemas(unittest.TestCase):
    """Test JSON schema definitions."""
    
    def test_turns_schema_exists(self):
        """Test that turns schema is defined."""
        from models.schemas import TURNS_SCHEMA
        self.assertIn("properties", TURNS_SCHEMA)
        self.assertIn("turns", TURNS_SCHEMA["properties"])
    
    def test_schema_lookup(self):
        """Test schema lookup by type."""
        from models.schemas import get_schema_by_type
        
        schema = get_schema_by_type("turns")
        self.assertIn("properties", schema)
        
        # Test invalid type
        with self.assertRaises(ValueError):
            get_schema_by_type("invalid_type")


class TestMockLambdaHandlers(unittest.TestCase):
    """Test Lambda handlers with mocked dependencies."""
    
    @patch('common.bedrock_client.BedrockClient')
    @patch('common.s3io.S3Client')
    def test_preprocess_turns_handler(self, mock_s3, mock_bedrock):
        """Test preprocess turns handler with mocks."""
        # Mock S3 client
        mock_s3_instance = Mock()
        mock_s3_instance.read_text_file.return_value = "Sample transcript text"
        mock_s3_instance.write_json_file.return_value = None
        mock_s3.return_value = mock_s3_instance
        
        # Mock Bedrock client
        mock_bedrock_instance = Mock()
        mock_response = {
            "meeting_id": "test-123",
            "time_zone": "America/New_York", 
            "turns": [
                {
                    "idx": 0,
                    "start_ts": "00:01:30",
                    "end_ts": "00:01:45",
                    "speaker": "Alice", 
                    "type": "question",
                    "question_likelihood": 0.8,
                    "text": "What time is the meeting?"
                }
            ]
        }
        mock_bedrock_instance.invoke_with_json_response.return_value = mock_response
        mock_bedrock.return_value = mock_bedrock_instance
        
        # Import and test handler
        from handlers.preprocess_turns import lambda_handler
        
        event = {
            "meeting_id": "test-123",
            "input_key": "transcripts/test.txt",
            "output_key": "outputs/turns.json"
        }
        
        result = lambda_handler(event, None)
        
        self.assertEqual(result['statusCode'], 200)
        self.assertEqual(result['meeting_id'], "test-123") 
        self.assertEqual(result['turn_count'], 1)


if __name__ == '__main__':
    # Run tests
    unittest.main()