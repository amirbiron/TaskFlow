"""
תזמון משימות רקע באמצעות APScheduler.

כרגע רצים שני jobs:
1. גיבוי MongoDB יומי
2. סריקת תזכורות טלגרם כל N דקות (לפי telegram_reminder_check_minutes)
"""
from __future__ import annotations

import logging
from datetime import datetime
from html import escape as html_escape
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from bson import ObjectId

from app.core.backup import run_backup
from app.core.config import get_settings
from app.core.database import get_database
from app.core import telegram

logger = logging.getLogger(__name__)

# סינגלטון - משותף לכל האפליקציה
_scheduler: Optional[AsyncIOScheduler] = None

BACKUP_JOB_ID = "mongodb_backup_daily"
TELEGRAM_REMINDERS_JOB_ID = "telegram_reminders"


async def _backup_job() -> None:
    """wrapper סביב run_backup שלוכד חריגות כדי שה-scheduler לא יכבה."""
    try:
        result = await run_backup()
        if not result.success:
            logger.error("גיבוי מתוזמן נכשל: %s", result.error)
    except Exception:  # noqa: BLE001
        logger.exception("חריגה לא צפויה ב-job של הגיבוי")


def _format_reminder_message(task: dict, project_name: Optional[str]) -> str:
    """בונה את גוף ההודעה לטלגרם (HTML parse_mode)."""
    title = html_escape(task.get("title") or "(ללא כותרת)")
    lines = [f"⏰ <b>תזכורת למשימה</b>", f"📝 {title}"]
    if project_name:
        lines.append(f"📁 פרויקט: {html_escape(project_name)}")
    due = task.get("due_date")
    if isinstance(due, datetime):
        lines.append(f"📅 תאריך יעד: {due.strftime('%Y-%m-%d')}")
    priority = task.get("priority")
    priority_labels = {"low": "נמוכה", "normal": "רגילה", "high": "גבוהה", "urgent": "דחוף"}
    if priority and priority != "normal":
        lines.append(f"⚡ עדיפות: {priority_labels.get(priority, priority)}")
    return "\n".join(lines)


async def _telegram_reminders_job() -> None:
    """סורק משימות שהגיע זמן התזכורת שלהן ושולח הודעת טלגרם.

    - מתעלם ממשימות בארכיון או שכבר הושלמו.
    - משתמש בשדה reminder_sent כדי לא לשלוח כפול.
    - מסמן reminder_sent=true רק אם השליחה הצליחה (כדי לאפשר retry בריצה הבאה).
    """
    if not telegram.is_enabled():
        return

    try:
        db = get_database()
        now = datetime.utcnow()
        query = {
            "reminder_date": {"$lte": now, "$ne": None},
            "reminder_sent": {"$ne": True},
            "status": {"$ne": "completed"},
            "archived": {"$ne": True},
        }
        cursor = db.tasks.find(query).limit(50)
        tasks = await cursor.to_list(length=50)
        if not tasks:
            return

        # שליפת שמות פרויקטים ב-bulk (חלק מההודעה)
        project_obj_ids = []
        seen = set()
        for t in tasks:
            pid = t.get("project_id")
            if pid and pid not in seen and ObjectId.is_valid(pid):
                project_obj_ids.append(ObjectId(pid))
                seen.add(pid)

        projects_by_id: dict[str, str] = {}
        if project_obj_ids:
            async for p in db.projects.find(
                {"_id": {"$in": project_obj_ids}}, {"name": 1}
            ):
                projects_by_id[str(p["_id"])] = p.get("name") or ""

        for task in tasks:
            project_name = projects_by_id.get(task.get("project_id") or "")
            message = _format_reminder_message(task, project_name)
            sent = await telegram.send_message(message)
            if sent:
                await db.tasks.update_one(
                    {"_id": task["_id"]},
                    {"$set": {"reminder_sent": True, "updated_at": datetime.utcnow()}},
                )
                logger.info("Telegram reminder sent for task %s", task["_id"])
            else:
                # נשמור על reminder_sent=false כדי לנסות שוב בריצה הבאה
                logger.warning("Telegram reminder send failed for task %s", task["_id"])
    except Exception:  # noqa: BLE001
        logger.exception("חריגה לא צפויה ב-job של תזכורות טלגרם")


def start_scheduler() -> None:
    """מאתחל ומריץ את ה-scheduler. נקרא מ-lifespan של FastAPI."""
    global _scheduler

    if _scheduler is not None:
        logger.warning("scheduler כבר רץ - מתעלם מקריאה כפולה")
        return

    settings = get_settings()

    # מתחילים scheduler רק אם יש לפחות job אחד שצריך לרוץ
    backup_active = settings.backup_enabled
    telegram_active = telegram.is_enabled()

    if not backup_active and not telegram_active:
        logger.info("אין jobs פעילים (גיבוי + טלגרם מושבתים) - לא מתזמן")
        return

    _scheduler = AsyncIOScheduler(timezone="UTC")

    if backup_active:
        _scheduler.add_job(
            _backup_job,
            trigger=CronTrigger(
                hour=settings.backup_hour,
                minute=settings.backup_minute,
                timezone="UTC",
            ),
            id=BACKUP_JOB_ID,
            name="גיבוי MongoDB יומי",
            replace_existing=True,
            # אם השרת היה כבוי בזמן הריצה ועלה אחר-כך - מותר לדלג, לא להריץ retroactively
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1,
        )
        logger.info(
            "scheduler: גיבוי יומי ב-%02d:%02d UTC",
            settings.backup_hour,
            settings.backup_minute,
        )

    if telegram_active:
        minutes = max(1, settings.telegram_reminder_check_minutes)
        _scheduler.add_job(
            _telegram_reminders_job,
            trigger=IntervalTrigger(minutes=minutes),
            id=TELEGRAM_REMINDERS_JOB_ID,
            name="סריקת תזכורות טלגרם",
            replace_existing=True,
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1,
        )
        logger.info("scheduler: תזכורות טלגרם כל %d דקות", minutes)

    _scheduler.start()


def stop_scheduler() -> None:
    """עוצר את ה-scheduler. נקרא מ-lifespan בכיבוי."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    logger.info("scheduler נעצר")


def get_next_run_time() -> Optional[str]:
    """מחזיר את זמן הריצה הבא של הגיבוי (ISO string), או None אם לא רץ."""
    if _scheduler is None:
        return None
    job = _scheduler.get_job(BACKUP_JOB_ID)
    if job is None or job.next_run_time is None:
        return None
    return job.next_run_time.isoformat()
