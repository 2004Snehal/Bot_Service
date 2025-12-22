from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from server.app.db.database import get_db
from server.app.db.models import Schedule, Bot, User
from server.app.models.schedule import ScheduleCreate, ScheduleResponse
from server.app.api.auth import get_current_user

router = APIRouter()

@router.post("/", response_model=ScheduleResponse)
def create_schedule(
    schedule: ScheduleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new schedule (bot must belong to current user)."""
    # Verify bot belongs to user
    bot = db.query(Bot).filter(
        Bot.id == schedule.bot_id,
        Bot.user_id == current_user.user_id
    ).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    db_schedule = Schedule(
        user_id=current_user.user_id,
        bot_id=schedule.bot_id,
        meetlink=schedule.meetlink,
        start_time=schedule.start_time,
        min_record_time_seconds=schedule.min_record_time_seconds,
        meeting_id=schedule.meeting_id,
        enable_recording=schedule.enable_recording,
        enable_transcript=schedule.enable_transcript,
        enable_speak=schedule.enable_speak
    )
    db.add(db_schedule)
    db.commit()
    db.refresh(db_schedule)
    return db_schedule

@router.get("/{schedule_id}", response_model=ScheduleResponse)
def get_schedule(
    schedule_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a schedule (must belong to current user)."""
    schedule = db.query(Schedule).filter(
        Schedule.id == schedule_id,
        Schedule.user_id == current_user.user_id
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule

@router.get("/", response_model=List[ScheduleResponse])
def list_schedules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all schedules for the current user."""
    return db.query(Schedule).filter(Schedule.user_id == current_user.user_id).all()

@router.delete("/{schedule_id}")
def delete_schedule(
    schedule_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a schedule (must belong to current user)."""
    schedule = db.query(Schedule).filter(
        Schedule.id == schedule_id,
        Schedule.user_id == current_user.user_id
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    
    db.delete(schedule)
    db.commit()
    return {"status": "deleted", "schedule_id": schedule_id}
