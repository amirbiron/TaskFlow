"""
לוגיקת גיבוי MongoDB באמצעות mongodump.

מבנה הגיבוי: ארכיון יחיד דחוס gzip לכל המסד, עם חותמת זמן בשם הקובץ.
לדוגמה: backup_2026-05-03_03-00-15.archive.gz

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
from urllib.parse import urlparse, urlunparse

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# פורמט שם קובץ גיבוי - חייב להישמר עקבי לטובת רוטציה ופענוח.
# כולל שניות כדי למנוע התנגשות בין גיבוי מתוזמן לידני באותה דקה.
BACKUP_FILENAME_PREFIX = "backup_"
BACKUP_FILENAME_SUFFIX = ".archive.gz"
BACKUP_TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"
# regex מקבל גם את הפורמט הישן (HH-MM) וגם החדש (HH-MM-SS) לטובת תאימות לאחור
_BACKUP_FILENAME_RE = re.compile(
    r"^backup_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}(-\d{2})?\.archive\.gz$"
)

# נעילה גלובלית - מונעת שתי הרצות מקבילות של mongodump (manual + scheduled,
# או שני triggers ידניים) שעלולות לדרוס אחת את הקובץ של השנייה ולפגוע בעומס DB.
_backup_lock = asyncio.Lock()

# הודעת שגיאה כשגיבוי כבר רץ - מזוהה ע"י ה-router כדי להחזיר 409 במקום 500.
BACKUP_ALREADY_RUNNING_ERROR = "גיבוי כבר רץ - נסה שוב מאוחר יותר"

# הנתיב הסטנדרטי שבו ה-build script של Render מתקין את mongodb-database-tools.
# משמש כ-fallback אוטומטי אם MONGODUMP_PATH לא הוגדר ב-env (למשל ב-Web Service
# שלא נוצר מ-Blueprint, ולכן env vars החדשים מ-render.yaml לא נטענו אוטומטית).
_RENDER_MONGODUMP_PATH = "/opt/render/project/.render/mongodb-tools/bin/mongodump"

# regex לסילוק credentials מ-URIs של MongoDB. mongodump (ובמיוחד שגיאות
# parsing/auth) עלול להחזיר את ה-URI ב-stderr - אסור לתת לו להגיע ללוגים,
# ל-API או ל-UI כי המסד מוגן בסיסמה ב-URI עצמו.
_MONGO_URI_CREDS_RE = re.compile(
    r"(mongodb(?:\+srv)?://)([^/@\s]+)@",
    re.IGNORECASE,
)


def _redact_secrets(text: str) -> str:
    """מסיר user:pass מ-URI של MongoDB לפני הצגה/לוג."""
    if not text:
        return text
    return _MONGO_URI_CREDS_RE.sub(r"\1***:***@", text)


def _resolve_mongodump_path() -> str:
    """
    מחזיר את הנתיב הסופי ל-mongodump:
    1. אם המשתמש הגדיר MONGODUMP_PATH לערך לא-ברירת-מחדל - מכבדים אותו.
    2. אחרת - אם הקובץ הסטנדרטי של Render install קיים, משתמשים בו.
    3. אחרת - נופלים על "mongodump" ב-PATH (לפיתוח מקומי).

    הכלל הזה מאפשר ל-deploy ב-Render לעבוד גם אם ה-env var לא הוגדר
    בלוח (למשל בשירותים שנוצרו לפני הוספת המשתנה ל-render.yaml).
    """
    settings = get_settings()
    if settings.mongodump_path != "mongodump":
        return settings.mongodump_path
    if Path(_RENDER_MONGODUMP_PATH).is_file():
        return _RENDER_MONGODUMP_PATH
    return settings.mongodump_path


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
    """בונה שם קובץ גיבוי על בסיס שעת UTC (precision של שניות)."""
    ts = (now or datetime.now(timezone.utc)).strftime(BACKUP_TIMESTAMP_FORMAT)
    return f"{BACKUP_FILENAME_PREFIX}{ts}{BACKUP_FILENAME_SUFFIX}"


def _build_dump_uri(uri: str, database_name: str) -> str:
    """
    מחליף את ה-path של ה-URI ב-database_name.

    נדרש כי mongodump 100.x דוחה את השילוב --uri + --db
    ("illegal argument combination"). חייבים להעביר את שם ה-DB
    דרך ה-URI עצמו.

    תמיד **דורסים** את ה-path הקיים (למשל '/test' שמגיע בברירת
    מחדל מ-Atlas) - מקור האמת הוא settings.database_name, וזה מה
    שהאפליקציה מתחברת אליו ב-database.py דרך client[database_name].
    אם נכבד את ה-path הקיים, הגיבוי יכול לטרגט מסד שונה מהאפליקציה
    בלי שהמשתמש ירגיש בכך - באג שקט וחמור.
    """
    parsed = urlparse(uri)
    return urlunparse(parsed._replace(path=f"/{database_name}"))


async def run_backup() -> BackupResult:
    """
    מריץ mongodump לתיקיית הגיבויים, מסובב גיבויים ישנים, ושומר תוצאה.

    מחזיר BackupResult עם success=True/False ופרטים. תמיד מחזיר אובייקט,
    גם בכישלון - לא זורק חריגה (ה-scheduler מבצע catch למעלה).

    אם גיבוי אחר כבר רץ - מחזיר מיידית BackupResult כושל (לא חוסם
    את הקריאה לזמן ארוך). זה מונע התנגשות בין trigger ידני למתוזמן.
    """
    global _last_result

    # בדיקה אופטימית - אם תפוס, חוסכים את כל הסטאפ ומחזירים מהר
    if _backup_lock.locked():
        return BackupResult(
            success=False,
            error=BACKUP_ALREADY_RUNNING_ERROR,
            finished_at=datetime.now(timezone.utc),
        )

    async with _backup_lock:
        # רשת בטיחות: גם אם _run_backup_locked יתפוצץ במקום שלא ציפינו
        # לו (למשל PermissionError מ-_ensure_backup_dir כשהדיסק מלא או
        # שאין הרשאות) - מחזירים BackupResult תקין במקום להפיץ חריגה.
        # זה מקיים את החוזה של run_backup ומבטיח ש-_last_result מתעדכן
        # כדי שמסך הניהול יציג את הכישלון, לא מידע ישן.
        try:
            return await _run_backup_locked()
        except Exception as exc:  # noqa: BLE001 - safety net, intentional
            msg = _redact_secrets(f"שגיאה בלתי צפויה בלוגיקת הגיבוי: {exc!r}")
            logger.exception(msg)
            result = BackupResult(
                success=False,
                error=msg,
                finished_at=datetime.now(timezone.utc),
            )
            _last_result = result
            return result


async def _run_backup_locked() -> BackupResult:
    """לוגיקת הגיבוי בפועל - תמיד נקראת מתוך ה-lock."""
    global _last_result

    settings = get_settings()
    started_at = datetime.now(timezone.utc)
    started_monotonic = asyncio.get_event_loop().time()

    backup_dir = _ensure_backup_dir()
    filename = _build_filename(started_at)
    target_path = backup_dir / filename

    dump_uri = _build_dump_uri(settings.mongodb_url, settings.database_name)
    mongodump_path = _resolve_mongodump_path()
    cmd = [
        mongodump_path,
        f"--uri={dump_uri}",
        "--gzip",
        f"--archive={target_path}",
    ]

    logger.info("מתחיל גיבוי MongoDB → %s (כלי: %s)", target_path, mongodump_path)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # mongodump כותב את ההתקדמות ל-stderr - שומרים לטובת אבחון
        _, stderr = await process.communicate()
        return_code = process.returncode

    except FileNotFoundError:
        # mongodump לא מותקן - הודעה ברורה למסך הניהול
        msg = f"mongodump לא נמצא בנתיב '{mongodump_path}'. ודא שהותקן ב-build."
        logger.error(msg)
        result = BackupResult(success=False, error=msg, finished_at=datetime.now(timezone.utc))
        _last_result = result
        return result
    except Exception as exc:  # noqa: BLE001 - רוצים לתפוס הכל כדי שה-scheduler ימשיך
        # repr של exception עלול לכלול את ה-cmd עם ה-URI - מסננים credentials
        msg = _redact_secrets(f"שגיאה בלתי צפויה בהרצת mongodump: {exc!r}")
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
        # mongodump עלול להחזיר את ה-URI עם credentials ב-stderr (במיוחד
        # בשגיאות auth/parsing) - מסננים לפני הצגה/לוג
        err_text = _redact_secrets(stderr.decode("utf-8", errors="replace").strip())
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
