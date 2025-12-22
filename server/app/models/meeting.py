from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class MeetingResponse(BaseModel):
    id: str
    user_id: str
    bot_id: str
    start_time: datetime
    end_time: Optional[datetime]
    transcript_file: Optional[str]
    transcript_summary: Optional[str]
    recording_file: Optional[str]
    screenshots_dir: Optional[str]
    status: str

    class Config:
        from_attributes = True
