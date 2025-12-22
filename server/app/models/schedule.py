from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class ScheduleBase(BaseModel):
    bot_id: str
    meetlink: str
    start_time: datetime
    min_record_time_seconds: int = 60
    # Optional client-provided meeting identifier
    meeting_id: Optional[str] = None
    # Feature flags
    enable_recording: bool = True
    enable_transcript: bool = True
    enable_speak: bool = True

class ScheduleCreate(ScheduleBase):
    pass

class ScheduleResponse(ScheduleBase):
    id: str
    user_id: str
    status: str

    class Config:
        from_attributes = True
