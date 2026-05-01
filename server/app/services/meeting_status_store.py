import logging
from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from server.app.config.settings import settings

logger = logging.getLogger(__name__)

_mongo_client: Optional[MongoClient] = None


def _normalize_user_id(user_id: str) -> Any:
    try:
        return ObjectId(user_id)
    except Exception:
        return user_id


def _get_meetings_collection() -> Optional[Collection]:
    mongo_url = settings.MONGO_URL
    mongo_db_name = settings.MONGO_DB_NAME

    if not mongo_url:
        logger.warning("MongoDB URL is not configured; meeting status will stay local.")
        return None

    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(mongo_url)

    return _mongo_client[mongo_db_name].meetings


def upsert_meeting_status(
    *,
    meeting_id: str,
    user_id: str,
    status: str,
    bot_id: Optional[str] = None,
    meetlink: Optional[str] = None,
    meeting_title: Optional[str] = None,
    calendar_event_id: Optional[str] = None,
    engaged: Optional[bool] = None,
    engaged_at: Optional[datetime] = None,
    auto_join: Optional[bool] = None,
    bot_config: Optional[Dict[str, Any]] = None,
    last_started_at: Optional[datetime] = None,
    last_stopped_at: Optional[datetime] = None,
    termination_reason: Optional[str] = None,
    error: Optional[str] = None,
) -> bool:
    collection = _get_meetings_collection()
    if collection is None:
        return False

    now = datetime.utcnow()
    normalized_user_id = _normalize_user_id(user_id)

    set_fields: Dict[str, Any] = {
        "status": status,
        "updated_at": now,
    }

    if bot_id is not None:
        set_fields["bot_id"] = bot_id
        set_fields["assigned_bot_id"] = bot_id
    if meetlink is not None:
        set_fields["meetlink"] = meetlink
    if meeting_title is not None:
        set_fields["meeting_title"] = meeting_title
    if calendar_event_id is not None:
        set_fields["calendar_event_id"] = calendar_event_id
    if engaged is not None:
        set_fields["engaged"] = engaged
    if engaged_at is not None:
        set_fields["engaged_at"] = engaged_at
    if auto_join is not None:
        set_fields["auto_join"] = auto_join
    if bot_config is not None:
        set_fields["bot_config"] = bot_config
    if last_started_at is not None:
        set_fields["last_started_at"] = last_started_at
    if last_stopped_at is not None:
        set_fields["last_stopped_at"] = last_stopped_at
    if termination_reason is not None:
        set_fields["termination_reason"] = termination_reason
    if error is not None:
        set_fields["error"] = error

    set_on_insert: Dict[str, Any] = {
        "meeting_id": meeting_id,
        "user_id": normalized_user_id,
        "created_at": now,
    }

    if bot_id is not None:
        set_on_insert["bot_id"] = bot_id
        set_on_insert["assigned_bot_id"] = bot_id
    if meetlink is not None:
        set_on_insert["meetlink"] = meetlink
    if meeting_title is not None:
        set_on_insert["meeting_title"] = meeting_title
    if calendar_event_id is not None:
        set_on_insert["calendar_event_id"] = calendar_event_id
    if engaged is not None:
        set_on_insert["engaged"] = engaged
    if engaged_at is not None:
        set_on_insert["engaged_at"] = engaged_at
    if auto_join is not None:
        set_on_insert["auto_join"] = auto_join
    if bot_config is not None:
        set_on_insert["bot_config"] = bot_config
    if last_started_at is not None:
        set_on_insert["last_started_at"] = last_started_at
    if last_stopped_at is not None:
        set_on_insert["last_stopped_at"] = last_stopped_at
    if termination_reason is not None:
        set_on_insert["termination_reason"] = termination_reason
    if error is not None:
        set_on_insert["error"] = error

    try:
        collection.update_one(
            {"meeting_id": meeting_id},
            {"$set": set_fields, "$setOnInsert": set_on_insert},
            upsert=True,
        )
        return True
    except PyMongoError as exc:
        logger.error(f"Failed to update meeting status in MongoDB: {exc}")
        return False


def get_latest_meeting_status_for_bot(
    bot_id: str,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    collection = _get_meetings_collection()
    if collection is None:
        return None

    query: Dict[str, Any] = {
        "$or": [
            {"bot_id": bot_id},
            {"assigned_bot_id": bot_id},
        ]
    }
    if user_id is not None:
        query["user_id"] = _normalize_user_id(user_id)

    meeting = collection.find_one(
        query,
        sort=[("updated_at", -1), ("created_at", -1)],
    )

    if not meeting:
        return None

    return {
        "meeting_id": meeting.get("meeting_id"),
        "status": meeting.get("status"),
        "engaged": meeting.get("engaged", False),
        "meeting_title": meeting.get("meeting_title"),
        "meetlink": meeting.get("meetlink"),
        "user_id": meeting.get("user_id"),
        "bot_id": meeting.get("bot_id") or meeting.get("assigned_bot_id"),
        "updated_at": meeting.get("updated_at"),
        "created_at": meeting.get("created_at"),
        "last_started_at": meeting.get("last_started_at"),
        "last_stopped_at": meeting.get("last_stopped_at"),
        "termination_reason": meeting.get("termination_reason"),
        "error": meeting.get("error"),
    }