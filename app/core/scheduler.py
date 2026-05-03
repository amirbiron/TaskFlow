"""
תזמון משימות רקע באמצעות APScheduler.

כרגע רץ רק job אחד: גיבוי MongoDB יומי. מבנה הקובץ נשאר גנרי
כדי שיהיה קל להוסיף jobs נוספים בעתיד (תזכורות טלגרם וכו').
"""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.backup import run_backup
from app.core.config import get_settings

logger = logging.getLogger(__name__)

# סינגלטון - משותף לכל האפליקציה
_scheduler: Optional[AsyncIOScheduler] = None

BACKUP_JOB_ID = "mongodb_backup_daily"


async def _backup_job() -> None:
    """wrapper סביב run_backup שלוכד חריגות כדי שה-scheduler לא יכבה."""
    try:
        result = await run_backup()
        if not result.success:
            logger.error("גיבוי מתוזמן נכשל: %s", result.error)
    except Exception:  # noqa: BLE001
        logger.exception("חריגה לא צפויה ב-job של הגיבוי")


def start_scheduler() -> None:
    """מאתחל ומריץ את ה-scheduler. נקרא מ-lifespan של FastAPI."""
    global _scheduler

    if _scheduler is not None:
        logger.warning("scheduler כבר רץ - מתעלם מקריאה כפולה")
        return

    settings = get_settings()
    if not settings.backup_enabled:
        logger.info("גיבוי מושבת (BACKUP_ENABLED=false) - לא מתזמן")
        return

    _scheduler = AsyncIOScheduler(timezone="UTC")
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
    _scheduler.start()
    logger.info(
        "scheduler הופעל - גיבוי יומי ב-%02d:%02d UTC",
        settings.backup_hour,
        settings.backup_minute,
    )


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
