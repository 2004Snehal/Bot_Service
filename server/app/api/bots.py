from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
from server.app.db.database import get_db
from server.app.db.models import Bot, User, Meeting
from server.app.models.bot import BotCreate, BotResponse, BotStartRequest
from server.app.services.bot_runner import start_bot_thread
from server.app.services.session_manager import session_manager
from server.app.api.auth import get_current_user

router = APIRouter()


@router.get(
    "/",
    response_model=List[BotResponse],
    responses={
        200: {"description": "List of user's bots"},
        401: {"description": "Invalid or missing API key"}
    }
)
def list_bots(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    List all bots owned by the current user.
    
    Requires: X-API-Key header
    """
    bots = db.query(Bot).filter(Bot.user_id == current_user.user_id).all()
    return bots


@router.post(
    "/",
    response_model=BotResponse,
    responses={
        200: {"description": "Bot created successfully"},
        401: {"description": "Invalid or missing API key"}
    }
)
def create_bot(
    bot: BotCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new bot configuration for the current user."""
    db_bot = Bot(
        name=bot.name,
        system_prompt=bot.system_prompt,
        user_id=current_user.user_id
    )
    db.add(db_bot)
    db.commit()
    db.refresh(db_bot)
    return db_bot


@router.get("/{bot_id}", response_model=BotResponse)
def get_bot(
    bot_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a bot by ID (must belong to current user)."""
    bot = db.query(Bot).filter(
        Bot.id == bot_id,
        Bot.user_id == current_user.user_id
    ).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot


@router.delete("/{bot_id}")
def delete_bot(
    bot_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a bot configuration (must belong to current user)."""
    bot = db.query(Bot).filter(
        Bot.id == bot_id,
        Bot.user_id == current_user.user_id
    ).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    # Check if bot is running
    if session_manager.get_bot(bot_id):
        raise HTTPException(status_code=400, detail="Cannot delete a running bot. Stop it first.")
    
    db.delete(bot)
    db.commit()
    return {"status": "deleted", "bot_id": bot_id}


@router.post("/{bot_id}/start")
def start_bot(
    bot_id: str,
    request: BotStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Start a bot to join a meeting.
    
    Request must include:
    - meetlink: Google Meet URL
    - user_id: Client-provided user ID
    - meeting_id: Client-provided meeting ID
    - enable_recording, enable_transcript, enable_speak (optional)
    """
    # Verify bot belongs to user (using current_user.user_id now)
    bot = db.query(Bot).filter(
        Bot.id == bot_id,
        Bot.user_id == current_user.user_id
    ).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    # Check if bot is already running
    if session_manager.get_bot(bot_id):
        raise HTTPException(status_code=400, detail="Bot is already running")
    
    # Verify user_id matches authenticated user
    if request.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="user_id mismatch")
    
    # Check if meeting_id already exists
    existing_meeting = db.query(Meeting).filter(Meeting.meeting_id == request.meeting_id).first()
    if existing_meeting:
        raise HTTPException(status_code=400, detail="meeting_id already exists")
    
    # Create meeting record with client-provided meeting_id
    meeting_record = Meeting(
        meeting_id=request.meeting_id,
        user_id=request.user_id,
        bot_id=bot_id,
        status="starting",
        start_time=datetime.utcnow(),
        recording_enabled=request.enable_recording,
        transcript_enabled=request.enable_transcript,
        speak_enabled=request.enable_speak
    )
    db.add(meeting_record)
    db.commit()
    db.refresh(meeting_record)
    
    # Start bot with all parameters
    start_bot_thread(
        user_id=request.user_id,
        bot_id=bot_id,
        meeting_id=request.meeting_id,
        meetlink=request.meetlink,
        min_record_time=request.min_record_time,
        bot_name=bot.name,
        system_prompt=bot.system_prompt,
        enable_recording=request.enable_recording,
        enable_transcript=request.enable_transcript,
        enable_speak=request.enable_speak
    )
    return {
        "status": "started",
        "bot_id": bot_id,
        "meeting_id": request.meeting_id,
        "user_id": request.user_id,
        "meetlink": request.meetlink,
        "enable_recording": request.enable_recording,
        "enable_transcript": request.enable_transcript,
        "enable_speak": request.enable_speak
    }


@router.post("/{bot_id}/stop")
def stop_bot(
    bot_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Stop a running bot (must belong to current user)."""
    # Verify ownership
    bot = db.query(Bot).filter(
        Bot.id == bot_id,
        Bot.user_id == current_user.user_id
    ).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    success = session_manager.stop_bot(bot_id)
    if not success:
        raise HTTPException(status_code=400, detail="Bot is not running or could not be stopped")
    return {"status": "stopping", "bot_id": bot_id}


@router.get("/{bot_id}/status")
def get_bot_status(
    bot_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the status of a bot (must belong to current user)."""
    # Verify ownership
    bot = db.query(Bot).filter(
        Bot.id == bot_id,
        Bot.user_id == current_user.user_id
    ).first()
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    
    bot_data = session_manager.get_bot(bot_id)
    if bot_data:
        return {"status": "running", "bot_id": bot_id}
    return {"status": "idle", "bot_id": bot_id}
