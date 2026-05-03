"""
לוגיקת גיבוי MongoDB - מימוש Python נטו עם motor + zipfile.

לא נדרש כלי חיצוני (mongodump). הקובץ הוא zip סטנדרטי שניתן לפתוח
בקליק כפול בכל מערכת הפעלה ולעיין בו ידנית.

מבנה הארכיון:
    backup_2026-05-03_03-00-15.zip
    ├── _meta.json          (גרסה, תאריך, ספירת רשומות לכל collection)
    ├── clients.json
    ├── projects.json
    ├── tasks.json
    ├── tags.json
    ├── task_comments.json
    └── ...

פורמט הרשומות: BSON Extended JSON v2 (canonical) - תומך ב-ObjectId,
datetime וכל סוגי BSON. ניתן לטעון חזרה דרך bson.json_util.

שחזור:
    python scripts/restore_backup.py /path/to/backup.zip
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import zipfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bson import json_util

from app.core.config import get_settings
from app.core.database import get_database

logger = logging.getLogger(__name__)

# פורמט שם קובץ גיבוי - חייב להישמר עקבי לטובת רוטציה ופענוח.
# כולל שניות כדי למנוע התנגשות בין גיבוי מתוזמן לידני באותה דקה.
BACKUP_FILENAME_PREFIX = "backup_"
BACKUP_FILENAME_SUFFIX = ".zip"
BACKUP_TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"
_BACKUP_FILENAME_RE = re.compile(
    r"^backup_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.zip$"
)

# גרסה של פורמט הגיבוי - לחזרת תאימות בעתיד אם נשנה את המבנה
BACKUP_FORMAT_VERSION = 1

# נעילה גלובלית - מונעת שתי הרצות מקבילות (manual+scheduled או manual+manual)
# שעלולות לדרוס אחת את הקובץ של השנייה, לעמיס על ה-DB או ליצור גיבוי לא עקבי.
_backup_lock = asyncio.Lock()

# הודעת שגיאה כשגיבוי כבר רץ - מזוהה ע"י ה-router כדי להחזיר 409 במקום 500.
BACKUP_ALREADY_RUNNING_ERROR = "גיבוי כבר רץ - נסה שוב מאוחר יותר"


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
    collections_count: int = 0
    documents_count: int = 0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "duration_seconds": round(self.duration_seconds, 2),
            "error": self.error,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "collections_count": self.collections_count,
            "documents_count": self.documents_count,
        }


# מחזיק את התוצאה האחרונה בזיכרון - לשימוש מסך הניהול
_last_result: Optional[BackupResult] = None


def get_last_result() -> Optional[BackupResult]:
    """מחזיר את תוצאת הגיבוי האחרון שרץ (None אם עוד לא רץ מאז startup)."""
    return _last_result


def _ensure_backup_dir() -> Path:
    """מוודא שתיקיית הגיבויים קיימת ומחזיר אותה."""
    settings = get_settings()
    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def is_safe_backup_filename(filename: str) -> bool:
    """בדיקת בטיחות לשם קובץ - חייב להתאים לפורמט הסטנדרטי שלנו.
    מונע ניסיונות path traversal דרך ה-API."""
    return bool(_BACKUP_FILENAME_RE.match(filename))


def _build_filename(now: Optional[datetime] = None) -> str:
    """בונה שם קובץ גיבוי על בסיס שעת UTC (precision של שניות)."""
    ts = (now or datetime.now(timezone.utc)).strftime(BACKUP_TIMESTAMP_FORMAT)
    return f"{BACKUP_FILENAME_PREFIX}{ts}{BACKUP_FILENAME_SUFFIX}"


async def _dump_collection_to_string(db, coll_name: str) -> tuple[str, int]:
    """
    שולף את כל המסמכים של collection ומחזיר (json_string, doc_count).
    מחזיר Extended JSON v2 (canonical) - פורמט שמשמר טיפוסי BSON.
    """
    docs = []
    cursor = db[coll_name].find({})
    async for doc in cursor:
        docs.append(doc)
    # json_util.dumps מתרגם ObjectId/datetime/Decimal128 וכו' ל-Extended JSON
    return json_util.dumps(docs, indent=2, ensure_ascii=False), len(docs)


async def _write_backup_zip(target_path: Path) -> tuple[int, int]:
    """
    כותב את כל ה-collections של המסד ל-zip בנתיב target_path.
    מחזיר (collections_count, documents_count_total).

    כותב ל-.partial ואז עושה rename אטומי - מונע קובץ חלקי בכישלון.
    הדחיסה היא ZIP_DEFLATED עם רמה 6 (אותו אלגוריתם של gzip, רק עטוף ב-zip).
    """
    db = get_database()
    if db is None:
        raise RuntimeError("חיבור למסד לא מאותחל - ודא ש-connect_to_mongo רץ ב-startup")

    collections = sorted(await db.list_collection_names())
    meta = {
        "format_version": BACKUP_FORMAT_VERSION,
        "format": "bson_extended_json_v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database_name": get_settings().database_name,
        "collections": {},  # יתמלא עם ספירות
    }
    total_docs = 0

    # rename אטומי: כותבים ל-.partial, ואם הצלחנו - rename. כך אם משהו נכשל
    # באמצע, לא יישאר קובץ חלקי שיציג את עצמו כגיבוי תקין ברשימה.
    tmp_path = target_path.with_name(target_path.name + ".partial")
    try:
        with zipfile.ZipFile(
            tmp_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as zf:
            for coll_name in collections:
                json_str, doc_count = await _dump_collection_to_string(db, coll_name)
                zf.writestr(f"{coll_name}.json", json_str)
                meta["collections"][coll_name] = doc_count
                total_docs += doc_count
            # _meta.json נכתב אחרון, אחרי שיש לנו את כל הספירות
            zf.writestr("_meta.json", json.dumps(meta, indent=2, ensure_ascii=False))
        tmp_path.replace(target_path)
    except Exception:
        # ניקוי קובץ חלקי לפני הפצת החריגה
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise

    return len(collections), total_docs


async def run_backup() -> BackupResult:
    """
    מריץ גיבוי Python נטו לתיקיית הגיבויים, מסובב גיבויים ישנים, ושומר תוצאה.

    מחזיר BackupResult עם success=True/False ופרטים. תמיד מחזיר אובייקט,
    גם בכישלון - לא זורק חריגה (ה-scheduler מבצע catch למעלה).

    אם גיבוי אחר כבר רץ - מחזיר מיידית BackupResult כושל (לא חוסם
    את הקריאה לזמן ארוך). זה מונע התנגשות בין trigger ידני למתוזמן.
    """
    global _last_result

    if _backup_lock.locked():
        return BackupResult(
            success=False,
            error=BACKUP_ALREADY_RUNNING_ERROR,
            finished_at=datetime.now(timezone.utc),
        )

    async with _backup_lock:
        # רשת בטיחות: מבטיחה שאף חריגה לא תפרוץ מ-run_backup, ושמסך הניהול
        # יראה כישלון אמיתי במקום להישאר עם המידע מהריצה הקודמת.
        try:
            return await _run_backup_locked()
        except Exception as exc:  # noqa: BLE001 - safety net, intentional
            msg = f"שגיאה בלתי צפויה בלוגיקת הגיבוי: {exc!r}"
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

    logger.info("מתחיל גיבוי MongoDB → %s", target_path)

    try:
        collections_count, documents_count = await _write_backup_zip(target_path)
    except Exception as exc:  # noqa: BLE001
        msg = f"גיבוי נכשל: {exc!r}"
        logger.exception(msg)
        result = BackupResult(
            success=False,
            error=msg,
            finished_at=datetime.now(timezone.utc),
        )
        _last_result = result
        return result

    duration = asyncio.get_event_loop().time() - started_monotonic
    finished_at = datetime.now(timezone.utc)
    size_bytes = target_path.stat().st_size if target_path.exists() else 0

    logger.info(
        "גיבוי הושלם: %s (%d collections, %d docs, %d bytes, %.2fs)",
        filename, collections_count, documents_count, size_bytes, duration,
    )

    # רוטציה - מוחק קבצים מעבר ל-retention. לא נחשב לכישלון אם נופל.
    try:
        deleted = rotate_backups(settings.backup_retention_days)
        if deleted:
            logger.info("נמחקו %d גיבויים ישנים: %s", len(deleted), deleted)
    except Exception:  # noqa: BLE001
        logger.exception("שגיאה ברוטציית גיבויים")

    result = BackupResult(
        success=True,
        filename=filename,
        size_bytes=size_bytes,
        duration_seconds=duration,
        finished_at=finished_at,
        collections_count=collections_count,
        documents_count=documents_count,
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
