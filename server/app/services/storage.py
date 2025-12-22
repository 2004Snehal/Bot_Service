"""
Cloud Storage Service for CueMeet Bot
======================================

Handles uploads to AWS S3 for meeting recordings and transcripts.
All data is stored in S3 with structure: s3://bucket/{user_id}/{meeting_id}/
"""

import os
import logging
import json
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def upload_meeting_to_s3(file_path: str, user_id: str, meeting_id: str, file_type: str = "recording") -> Optional[str]:
    """
    Upload a file to AWS S3.
    
    Args:
        file_path: Local file path
        user_id: User ID for S3 organization
        meeting_id: Meeting ID for S3 organization
        file_type: "recording" or "transcript"
    
    Returns:
        S3 URL if successful, None otherwise
    """
    # Check if S3 is configured
    from server.app.config.settings import settings
    
    if not all([settings.AWS_ACCESS_KEY_ID, settings.AWS_SECRET_ACCESS_KEY, settings.S3_BUCKET_NAME]):
        logger.warning("S3 not configured. Skipping upload.")
        return None
    
    try:
        import boto3
        from botocore.exceptions import ClientError
        
        s3_client = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION
        )
        
        # S3 key structure: {user_id}/{meeting_id}/{file_type}_{meeting_id}.ext
        file_ext = os.path.splitext(file_path)[1]
        s3_key = f"{user_id}/{meeting_id}/{file_type}_{meeting_id}{file_ext}"
        
        # Determine content type
        content_type_map = {
            ".mp4": "video/mp4",
            ".opus": "audio/opus",
            ".wav": "audio/wav",
            ".json": "application/json"
        }
        content_type = content_type_map.get(file_ext, "application/octet-stream")
        
        # Upload to S3
        logger.info(f"Uploading {file_path} to S3: s3://{settings.S3_BUCKET_NAME}/{s3_key}")
        
        with open(file_path, 'rb') as f:
            s3_client.upload_fileobj(
                f,
                settings.S3_BUCKET_NAME,
                s3_key,
                ExtraArgs={
                    'ContentType': content_type,
                    'Metadata': {
                        'user_id': user_id,
                        'meeting_id': meeting_id,
                        'file_type': file_type,
                        'upload_time': datetime.utcnow().isoformat()
                    }
                }
            )
        
        # Generate S3 URL
        s3_url = f"https://{settings.S3_BUCKET_NAME}.s3.{settings.AWS_REGION}.amazonaws.com/{s3_key}"
        logger.info(f"Successfully uploaded to S3: {s3_url}")
        
        return s3_url
        
    except ClientError as e:
        logger.error(f"S3 upload failed: {e}")
        return None
    except ImportError:
        logger.error("boto3 not installed. Install with: pip install boto3")
        return None
    except Exception as e:
        logger.error(f"Unexpected error during S3 upload: {e}")
        return None


# ============================================================================
# MONGODB FUNCTIONS (DEPRECATED - Using S3 only now)
# ============================================================================
# def save_transcript_to_mongo(transcript_file_path: str, user_id: str, meeting_id: str) -> Optional[str]:
#     """
#     Save transcript JSON to MongoDB.
#     
#     Args:
#         transcript_file_path: Path to transcript JSON file
#         user_id: User ID
#         meeting_id: Meeting ID
#     
#     Returns:
#         MongoDB document ID if successful, None otherwise
#     """
#     # Check if MongoDB is configured
#     from server.app.config.settings import settings
#     
#     if not settings.MONGODB_URI:
#         logger.warning("MongoDB not configured. Skipping transcript save.")
#         return None
#     
#     try:
#         from pymongo import MongoClient
#         from pymongo.errors import PyMongoError
#         
#         # Connect to MongoDB
#         client = MongoClient(settings.MONGODB_URI)
#         db = client[settings.MONGODB_DATABASE]
#         collection = db['transcripts']
#         
#         # Read transcript file
#         with open(transcript_file_path, 'r', encoding='utf-8') as f:
#             transcript_data = json.load(f)
#         
#         # Add metadata
#         document = {
#             "user_id": user_id,
#             "meeting_id": meeting_id,
#             "transcript": transcript_data,
#             "created_at": datetime.utcnow(),
#             "updated_at": datetime.utcnow()
#         }
#         
#         # Insert into MongoDB
#         logger.info(f"Saving transcript to MongoDB for meeting {meeting_id}")
#         result = collection.insert_one(document)
#         
#         logger.info(f"Transcript saved to MongoDB with ID: {result.inserted_id}")
#         return str(result.inserted_id)
#         
#     except PyMongoError as e:
#         logger.error(f"MongoDB save failed: {e}")
#         return None
#     except ImportError:
#         logger.error("pymongo not installed. Install with: pip install pymongo")
#         return None
#     except Exception as e:
#         logger.error(f"Unexpected error during MongoDB save: {e}")
#         return None


# def get_transcript_from_mongo(meeting_id: str) -> Optional[dict]:
#     """
#     Retrieve transcript from MongoDB by meeting ID.
#     
#     Args:
#         meeting_id: Meeting ID
#     
#     Returns:
#         Transcript data if found, None otherwise
#     """
#     from server.app.config.settings import settings
#     
#     if not settings.MONGODB_URI:
#         return None
#     
#     try:
#         from pymongo import MongoClient
#         
#         client = MongoClient(settings.MONGODB_URI)
#         db = client[settings.MONGODB_DATABASE]
#         collection = db['transcripts']
#         
#         document = collection.find_one({"meeting_id": meeting_id})
#         
#         if document:
#             return document.get("transcript")
#         return None
#         
#     except Exception as e:
#         logger.error(f"Error retrieving transcript from MongoDB: {e}")
#         return None
