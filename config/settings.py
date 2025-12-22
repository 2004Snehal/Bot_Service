from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from typing import Optional


class Settings(BaseSettings):
    """
    Configuration settings for the Google meeting bot.
    Uses pydantic for validation and environment variable loading.
    """

    # Logging Settings
    DEBUG: bool = Field(False, description="Logging level")
    HIGHLIGHT_PROJECT_ID: str = Field("HIGHLIGHT_PROJECT_ID", description="Highlight project ID")
    ENVIRONMENT_NAME: str = Field("ENVIRONMENT_NAME", description="Environment name")
    
    # API Keys for Audio/AI Services
    DEEPGRAM_API_KEY: Optional[str] = Field(None, description="Deepgram API key for speech-to-text")
    GROQ_API_KEY: Optional[str] = Field(None, description="Groq API key for LLM")
    TTS_MICROSERVICE_URL: str = Field("http://localhost:8000/generate-audio", description="TTS microservice URL")

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Ignore any extra env vars not defined here


@lru_cache()
def get_settings() -> Settings:
    """
    Creates and returns a cached instance of the Settings class.
    Uses environment variables and .env file for configuration.
    
    Returns:
        Settings: Configuration settings instance
    """
    load_dotenv()
    return Settings()