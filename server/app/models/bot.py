from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import uuid


# ============ User Models ============
class UserCreate(BaseModel):
    user_id: str  # Client provides user_id
    email: Optional[str] = None

class UserResponse(BaseModel):
    user_id: str  # Using user_id instead of id
    api_key: str
    created_at: datetime
    is_active: str

    class Config:
        from_attributes = True


# ============ Bot Models ============
class BotBase(BaseModel):
    name: str
    system_prompt: Optional[str] = None

class BotCreate(BotBase):
    pass

class BotResponse(BotBase):
    id: str
    user_id: str
    created_at: datetime

    class Config:
        from_attributes = True

class BotStartRequest(BaseModel):
    meetlink: str
    user_id: str  # Client provides user_id
    meeting_id: str  # Client provides meeting_id
    min_record_time: int = 60
    enable_recording: bool = True  # Enable video/audio recording
    enable_transcript: bool = True  # Enable transcript extraction
    enable_speak: bool = True  # Whether bot can speak or just listen
