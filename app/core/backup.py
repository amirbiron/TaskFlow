"""
לוגיקת גיבוי MongoDB באמצעות mongodump.

מבנה הגיבוי: ארכיון יחיד דחוס gzip לכל המסד, עם חותמת זמן בשם הקובץ.
לדוגמה: backup_2026-05-03_03-00.archive.gz

שחזור (ידני, לא דרך האפליקציה):
    mongorestore --gzip --archive=/path/to/backup.archive.gz \
        --uri "$MONGODB_URL"
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# פורמט שם קובץ גיבוי - חייב להישמר עקבי לטובת רוטציה ופענוח
BACKUP_FILENAME_PREFIX = "backup_"
BACKUP_FILENAME_SUFFIX = ".archive.gz"
BACKUP_TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M"
# regex מחמיר לשמות קבצי גיבוי - מונע ניסיונות path traversal דרך ה-API
_BACKUP_FILENAME_RE = re.compile(
    r"^backup_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}\.archive\.gz$"
)


@dataclass
class BackupInfo:
    """מטא-דאטה של קובץ גיבוי בודד - מוחזר ל-API ול-UI."""
    filename: str
    size_bytes: int
    created_at: datetime  # timezone-aware (UTC)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d


@dataclass
class BackupResult:
    """תוצאת ריצה של גיבוי בודד."""
    success: bool
    filename: Optional[str] = None
    size_bytes: int = 0
    duration_seconds: float = 0.0
    error: Optional[str] = None
    finished_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "duration_seconds": round(self.duration_seconds, 2),
            "error": self.error,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


# מחזיק את התוצאה האחרונה בזיכרון - לשימוש מסך הניהול
_last_result: Optional[BackupResult] = None


def get_last_result() -> Optional[BackupResult]:
    """מחזיר את תוצאת הגיבוי האחרון שרץ (None אם עוד לא רץ באז startup)."""
    return _last_result


def _ensure_backup_dir() -> Path:
    """מוודא שתיקיית הגיבויים קיימת ומחזיר אותה."""
    settings = get_settings()
    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def is_safe_backup_filename(filename: str) -> bool:
    """בדיקת בטיחות לשם קובץ - חייב להתאים לפורמט הסטנדרטי שלנו."""
    return bool(_BACKUP_FILENAME_RE.match(filename))


def _build_filename(now: Optional[datetime] = None) -> str:
    """בונה שם קובץ גיבוי על בסיס שעת UTC."""
    ts = (now or datetime.now(timezone.utc)).strftime(BACKUP_TIMESTAMP_FORMAT)
    return f"{BACKUP_FILENAME_PREFIX}{ts}{BACKUP_FILENAME_SUFFIX}"


async def run_backup() -> BackupResult:
    """
    מריץ mongodump לתיקיית הגיבויים, מסובב גיבויים ישנים, ושומר תוצאה.

    מחזיר BackupResult עם success=True/False ופרטים. תמיד מחזיר אובייקט,
    גם בכישלון - לא זורק חריגה (ה-scheduler מבצע catch למעלה).
    """
    global _last_result

    settings = get_settings()
    started_at = datetime.now(timezone.utc)
    started_monotonic = asyncio.get_event_loop().time()

    backup_dir = _ensure_backup_dir()
    filename = _build_filename(started_at)
    target_path = backup_dir / filename

    cmd = [
        settings.mongodump_path,
        f"--uri={settings.mongodb_url}",
        f"--db={settings.database_name}",
        "--gzip",
        f"--archive={target_path}",
    ]

    logger.info("מתחיל גיבוי MongoDB → %s", target_path)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # mongodump כותב את ההתקדמות ל-stderr - שומרים לטובת אבחון
        _, stderr = await process.communicate()
        return_code = process.returncode

    except FileNotFoundError as exc:
        # mongodump לא מותקן - הודעה ברורה למסך הניהול
        msg = f"mongodump לא נמצא בנתיב '{settings.mongodump_path}'. ודא שהותקן ב-build."
        logger.error(msg)
        result = BackupResult(success=False, error=msg, finished_at=datetime.now(timezone.utc))
        _last_result = result
        return result
    except Exception as exc:  # noqa: BLE001 - רוצים לתפוס הכל כדי שה-scheduler ימשיך
        msg = f"שגיאה בלתי צפויה בהרצת mongodump: {exc!r}"
        logger.exception(msg)
        result = BackupResult(success=False, error=msg, finished_at=datetime.now(timezone.utc))
        _last_result = result
        return result

    duration = asyncio.get_event_loop().time() - started_monotonic
    finished_at = datetime.now(timezone.utc)

    if return_code != 0:
        # ניקוי קובץ חלקי שנותר אחרי כישלון
        if target_path.exists():
            try:
                target_path.unlink()
            except OSError:
                pass
        err_text = stderr.decode("utf-8", errors="replace").strip()
        # mongodump מדפיס מעט מאוד שורות - שומרים את כולן
        msg = f"mongodump נכשל (exit={return_code}): {err_text[:1000]}"
        logger.error(msg)
        result = BackupResult(
            success=False,
            error=msg,
            duration_seconds=duration,
            finished_at=finished_at,
        )
        _last_result = result
        return result

    size_bytes = target_path.stat().st_size if target_path.exists() else 0
    logger.info("גיבוי הושלם: %s (%d bytes, %.2fs)", filename, size_bytes, duration)

    # רוטציה - מוחק קבצים מעבר ל-retention
    try:
        deleted = rotate_backups(settings.backup_retention_days)
        if deleted:
            logger.info("נמחקו %d גיבויים ישנים: %s", len(deleted), deleted)
    except Exception:  # noqa: BLE001
        # רוטציה כושלת לא צריכה להחשב ככישלון של הגיבוי עצמו
        logger.exception("שגיאה ברוטציית גיבויים")

    result = BackupResult(
        success=True,
        filename=filename,
        size_bytes=size_bytes,
        duration_seconds=duration,
        finished_at=finished_at,
    )
    _last_result = result
    return result


def list_backups() -> list[BackupInfo]:
    """
    מחזיר רשימת קבצי גיבוי בתיקייה, ממוין מהחדש לישן.
    מתעלם מקבצים שלא תואמים את פורמט השמות שלנו (אבטחה + ניקיון).
    """
    backup_dir = Path(get_settings().backup_dir)
    if not backup_dir.exists():
        return []

    items: list[BackupInfo] = []
    for entry in backup_dir.iterdir():
        if not entry.is_file() or not is_safe_backup_filename(entry.name):
            continue
        stat = entry.stat()
        items.append(
            BackupInfo(
                filename=entry.name,
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
        )

    items.sort(key=lambda b: b.created_at, reverse=True)
    return items


def rotate_backups(retention_days: int) -> list[str]:
    """
    מוחק קבצי גיבוי שיותר ישנים מ-retention_days. מחזיר רשימת שמות שנמחקו.
    הרוטציה מבוססת על mtime, לא על שם הקובץ - בטוח גם אם זמני המערכת השתנו.
    """
    if retention_days <= 0:
        return []

    cutoff_ts = datetime.now(timezone.utc).timestamp() - (retention_days * 86400)
    deleted: list[str] = []

    for backup in list_backups():
        if backup.created_at.timestamp() < cutoff_ts:
            path = Path(get_settings().backup_dir) / backup.filename
            try:
                path.unlink()
                deleted.append(backup.filename)
            except OSError as exc:
                logger.warning("לא ניתן למחוק %s: %s", backup.filename, exc)

    return deleted


def get_backup_path(filename: str) -> Optional[Path]:
    """
    מחזיר את הנתיב המלא של קובץ גיבוי, או None אם השם לא בטוח/הקובץ לא קיים.
    משמש את ה-endpoint של ההורדה.
    """
    if not is_safe_backup_filename(filename):
        return None
    path = Path(get_settings().backup_dir) / filename
    if not path.is_file():
        return None
    return path


def delete_backup(filename: str) -> bool:
    """מוחק גיבוי בודד. מחזיר True אם נמחק, False אם לא נמצא/לא בטוח."""
    path = get_backup_path(filename)
    if not path:
        return False
    try:
        path.unlink()
        return True
    except OSError as exc:
        logger.warning("לא ניתן למחוק %s: %s", filename, exc)
        return False
