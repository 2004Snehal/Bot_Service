import os
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Hicapy Bot API"
    DATABASE_URL: str = "sqlite:///./local.db"
    
    # API Keys (passed to bot containers)
    DEEPGRAM_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    TTS_MICROSERVICE_URL: str = "https://smolservice.onrender.com"
    
    # Server config
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    

    # SECURITY: Admin API key for user management
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    # MUST be set in production!
    ADMIN_API_KEY: Optional[str] = None
    
    # AWS S3 Configuration (using IAM roles)
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: Optional[str] = None
    
    # MongoDB Configuration (Optional - for transcript storage)
    MONGODB_URI: Optional[str] = None
    MONGODB_DATABASE: str = "cuemeet_transcripts"
    
    class Config:
        env_file = ".env"
        extra = "ignore"  # Ignore extra env vars not defined here

settings = Settings()
