import uuid
import secrets
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Enum, Boolean
from sqlalchemy.orm import relationship
from server.app.db.database import Base


class User(Base):
    """User model for multi-tenant support and API authentication."""
    __tablename__ = "users"

    user_id = Column(String, primary_key=True)  # Client-provided user_id
    email = Column(String, unique=True, index=True, nullable=True)
    api_key = Column(String, unique=True, index=True, default=lambda: f"cm_{secrets.token_urlsafe(32)}")
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(String, default="true")

    # Relationships
    bots = relationship("Bot", back_populates="user")
    meetings = relationship("Meeting", back_populates="user")
    schedules = relationship("Schedule", back_populates="user")


class Bot(Base):
    __tablename__ = "bots"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    name = Column(String, index=True)
    system_prompt = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="bots")

class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    bot_id = Column(String, ForeignKey("bots.id"))
    meeting_id = Column(String, nullable=True)  # Client-provided meeting_id
    meetlink = Column(String)
    start_time = Column(DateTime)
    min_record_time_seconds = Column(Integer, default=60)
    enable_recording = Column(Boolean, default=True)
    enable_transcript = Column(Boolean, default=True)
    enable_speak = Column(Boolean, default=True)
    status = Column(String, default="pending") # pending, running, completed, failed

    user = relationship("User", back_populates="schedules")
    bot = relationship("Bot")

class Meeting(Base):
    __tablename__ = "meetings"

    meeting_id = Column(String, primary_key=True)  # Client-provided meeting_id
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    bot_id = Column(String, ForeignKey("bots.id"))
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    
    # Local file paths (for development/backup)
    transcript_file = Column(String, nullable=True)
    recording_file = Column(String, nullable=True)
    
    # Cloud storage (S3 URLs) - Organized as {user_id}/{meeting_id}/
    transcript_s3_url = Column(String, nullable=True)
    recording_s3_url = Column(String, nullable=True)
    
    # Recording settings
    recording_enabled = Column(Boolean, default=True)
    transcript_enabled = Column(Boolean, default=True)
    speak_enabled = Column(Boolean, default=True)
    
    transcript_summary = Column(String, nullable=True)
    status = Column(String, default="running") # running, completed, failed

    user = relationship("User", back_populates="meetings")
    bot = relationship("Bot")
