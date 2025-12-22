from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from datetime import datetime
import uuid
from server.app.db.database import SessionLocal
from server.app.db.models import Schedule, Bot
from server.app.services.bot_runner import start_bot_thread
import logging

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

def check_schedules():
    db: Session = SessionLocal()
    try:
        now = datetime.utcnow()
        pending_schedules = db.query(Schedule).filter(
            Schedule.status == "pending",
            Schedule.start_time <= now
        ).all()

        for schedule in pending_schedules:
            logger.info(f"Starting scheduled bot for schedule {schedule.id}")
            bot = db.query(Bot).filter(Bot.id == schedule.bot_id).first()
            if bot:
                # Create a Meeting record for this schedule
                from server.app.db.models import Meeting
                meeting = Meeting(
                    meeting_id=schedule.meeting_id or str(uuid.uuid4()),
                    user_id=schedule.user_id,
                    bot_id=schedule.bot_id,
                    start_time=schedule.start_time,
                    recording_enabled=schedule.enable_recording if hasattr(schedule, 'enable_recording') else True,
                    transcript_enabled=schedule.enable_transcript if hasattr(schedule, 'enable_transcript') else True,
                    speak_enabled=schedule.enable_speak if hasattr(schedule, 'enable_speak') else True,
                    status="starting"
                )
                db.add(meeting)
                db.commit()
                db.refresh(meeting)

                # Start the bot with all relevant fields
                start_bot_thread(
                    user_id=schedule.user_id,
                    bot_id=bot.id,
                    meeting_id=meeting.meeting_id,
                    meetlink=schedule.meetlink,
                    min_record_time=schedule.min_record_time_seconds,
                    bot_name=bot.name,
                    system_prompt=getattr(bot, 'system_prompt', None),
                    enable_recording=getattr(schedule, 'enable_recording', True),
                    enable_transcript=getattr(schedule, 'enable_transcript', True),
                    enable_speak=getattr(schedule, 'enable_speak', True)
                )
                schedule.status = "running"
                db.commit()
            else:
                logger.error(f"Bot not found for schedule {schedule.id}")
                schedule.status = "failed"
                db.commit()
    except Exception as e:
        logger.error(f"Scheduler error: {e}")
    finally:
        db.close()

def start_scheduler():
    scheduler.add_job(check_schedules, 'interval', seconds=30)
    scheduler.start()
