"""
S3 I/O utilities for GRiST meeting pipeline.

Provides convenient functions for reading and writing files to S3,
with proper error handling and type hints.
"""

import json
import os
from typing import Dict, Any, Optional, Union
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import logging

logger = logging.getLogger(__name__)


class S3Client:
    """Client for S3 operations in the meeting pipeline."""
    
    def __init__(self, bucket_name: Optional[str] = None, region: Optional[str] = None):
        """
        Initialize S3 client.
        
        Args:
            bucket_name: S3 bucket name (defaults to environment variable)
            region: AWS region (defaults to environment variable)
        """
        self.bucket_name = bucket_name or os.getenv('BUCKET')
        self.region = region or os.getenv('REGION', 'us-east-1')
        
        if not self.bucket_name:
            raise ValueError("BUCKET environment variable is required")
            
        self.client = boto3.client('s3', region_name=self.region)
        
    def read_text_file(self, key: str) -> str:
        """
        Read a text file from S3.
        
        Args:
            key: S3 object key/path
            
        Returns:
            File contents as string
            
        Raises:
            Exception: If file cannot be read
        """
        try:
            response = self.client.get_object(Bucket=self.bucket_name, Key=key)
            return response['Body'].read().decode('utf-8')
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchKey':
                raise FileNotFoundError(f"File not found: s3://{self.bucket_name}/{key}")
            else:
                logger.error(f"S3 error reading {key}: {e}")
                raise Exception(f"Failed to read file from S3: {e}")
        except Exception as e:
            logger.error(f"Unexpected error reading {key}: {e}")
            raise
            
    def write_text_file(self, key: str, content: str, content_type: str = 'text/plain') -> None:
        """
        Write a text file to S3.
        
        Args:
            key: S3 object key/path
            content: Text content to write
            content_type: MIME content type
            
        Raises:
            Exception: If file cannot be written
        """
        try:
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=content.encode('utf-8'),
                ContentType=content_type
            )
            logger.info(f"Successfully wrote file: s3://{self.bucket_name}/{key}")
        except ClientError as e:
            logger.error(f"S3 error writing {key}: {e}")
            raise Exception(f"Failed to write file to S3: {e}")
        except Exception as e:
            logger.error(f"Unexpected error writing {key}: {e}")
            raise
            
    def read_json_file(self, key: str) -> Dict[str, Any]:
        """
        Read and parse a JSON file from S3.
        
        Args:
            key: S3 object key/path
            
        Returns:
            Parsed JSON data
            
        Raises:
            Exception: If file cannot be read or parsed
        """
        try:
            content = self.read_text_file(key)
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from {key}: {e}")
            raise Exception(f"Invalid JSON in file {key}: {e}")
            
    def write_json_file(self, key: str, data: Dict[str, Any], indent: int = 2) -> None:
        """
        Write data as JSON file to S3.
        
        Args:
            key: S3 object key/path
            data: Data to serialize as JSON
            indent: JSON indentation for readability
            
        Raises:
            Exception: If data cannot be serialized or written
        """
        try:
            content = json.dumps(data, indent=indent, ensure_ascii=False)
            self.write_text_file(key, content, content_type='application/json')
        except TypeError as e:
            logger.error(f"Failed to serialize data to JSON: {e}")
            raise Exception(f"Cannot serialize data to JSON: {e}")
            
    def file_exists(self, key: str) -> bool:
        """
        Check if a file exists in S3.
        
        Args:
            key: S3 object key/path
            
        Returns:
            True if file exists, False otherwise
        """
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            else:
                # Re-raise other errors (permissions, etc.)
                raise
                
    def get_file_size(self, key: str) -> int:
        """
        Get file size in bytes.
        
        Args:
            key: S3 object key/path
            
        Returns:
            File size in bytes
            
        Raises:
            Exception: If file does not exist or cannot be accessed
        """
        try:
            response = self.client.head_object(Bucket=self.bucket_name, Key=key)
            return response['ContentLength']
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                raise FileNotFoundError(f"File not found: s3://{self.bucket_name}/{key}")
            else:
                raise Exception(f"Cannot access file metadata: {e}")