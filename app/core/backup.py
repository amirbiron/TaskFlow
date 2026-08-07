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

עותק חיצוני:
    אם BACKUP_R2_ENABLED דלוק ומוגדר BACKUP_R2_BUCKET, כל גיבוי מוצלח מועלה
    גם לבאקט R2 פרטי. כשל בהעלאה לא מפיל את הגיבוי - הקובץ המקומי תקין -
    אבל נרשם ב-BackupResult ומוצג במסך הניהול.

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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from bson import json_util

from app.core import r2
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
    # מצב העותק החיצוני. success למעלה מתייחס לגיבוי המקומי בלבד -
    # העלאה שנכשלה לא הופכת גיבוי תקין לכושל, אבל חייבת להיות גלויה.
    r2_enabled: bool = False
    r2_uploaded: bool = False
    r2_key: Optional[str] = None
    r2_error: Optional[str] = None

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
            "r2_enabled": self.r2_enabled,
            "r2_uploaded": self.r2_uploaded,
            "r2_key": self.r2_key,
            "r2_error": self.r2_error,
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


# ---------------------------------------------------------------------------
# עותק חיצוני ב-R2
# ---------------------------------------------------------------------------

def r2_backup_enabled() -> bool:
    """האם להעלות עותק ל-R2. דורש גם דגל דלוק וגם באקט מפורש.

    הבאקט חייב להיות מפורש בכוונה: ברירת מחדל לבאקט של הקבצים המצורפים
    הייתה שמה את כל המסד בבאקט עם גישה ציבורית.
    """
    settings = get_settings()
    return bool(settings.backup_r2_enabled and settings.backup_r2_bucket)


def _r2_prefix() -> str:
    """ה-prefix בבאקט, מנורמל בלי לוכסנים מיותרים. ריק => שורש הבאקט."""
    return (get_settings().backup_r2_prefix or "").strip("/")


def _r2_key_for(filename: str) -> str:
    prefix = _r2_prefix()
    return f"{prefix}/{filename}" if prefix else filename


async def _upload_backup_to_r2(path: Path, filename: str) -> str:
    """מעלה קובץ גיבוי לבאקט ה-R2 ומחזיר את ה-key שנכתב."""
    settings = get_settings()
    return await r2.upload_file(
        str(path),
        _r2_key_for(filename),
        bucket=settings.backup_r2_bucket,
        content_type="application/zip",
    )


async def rotate_r2_backups(retention_days: int) -> list[str]:
    """
    מוחק גיבויים ישנים מהבאקט. מחזיר רשימת keys שנמחקו.

    מוחק רק אובייקטים ששם הקובץ שלהם תואם את פורמט הגיבוי שלנו - כך שקובץ
    זר שהונח באותו prefix לא נמחק בטעות. הגיל נקבע לפי LastModified של
    האובייקט, לא לפי שם הקובץ, מאותו נימוק כמו ברוטציה המקומית.
    """
    if retention_days <= 0:
        return []

    settings = get_settings()
    prefix = _r2_prefix()
    objects = await r2.list_objects(
        f"{prefix}/" if prefix else "", bucket=settings.backup_r2_bucket
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted: list[str] = []

    for obj in objects:
        if not is_safe_backup_filename(obj["key"].rsplit("/", 1)[-1]):
            continue
        last_modified = obj.get("last_modified")
        if not isinstance(last_modified, datetime) or last_modified >= cutoff:
            continue
        try:
            await r2.delete_object(obj["key"], bucket=settings.backup_r2_bucket)
            deleted.append(obj["key"])
        except r2.R2Error as exc:
            logger.warning("לא ניתן למחוק מ-R2 את %s: %s", obj["key"], exc)

    return deleted


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

    dump_duration = asyncio.get_event_loop().time() - started_monotonic
    size_bytes = target_path.stat().st_size if target_path.exists() else 0

    logger.info(
        "גיבוי הושלם: %s (%d collections, %d docs, %d bytes, %.2fs)",
        filename, collections_count, documents_count, size_bytes, dump_duration,
    )

    # רוטציה - מוחק קבצים מעבר ל-retention. לא נחשב לכישלון אם נופל.
    try:
        deleted = rotate_backups(settings.backup_retention_days)
        if deleted:
            logger.info("נמחקו %d גיבויים ישנים: %s", len(deleted), deleted)
    except Exception:  # noqa: BLE001
        logger.exception("שגיאה ברוטציית גיבויים")

    # העלאת עותק חיצוני. הגיבוי המקומי כבר תקין בשלב הזה, ולכן כשל כאן
    # מתועד אבל לא הופך את התוצאה לכושלת.
    r2_enabled = r2_backup_enabled()
    r2_uploaded = False
    r2_key: Optional[str] = None
    r2_error: Optional[str] = None

    if r2_enabled:
        try:
            r2_key = await _upload_backup_to_r2(target_path, filename)
            r2_uploaded = True
            logger.info("גיבוי הועלה ל-R2: %s", r2_key)
        except Exception as exc:  # noqa: BLE001
            r2_error = f"העלאה ל-R2 נכשלה: {exc!r}"
            logger.exception(r2_error)

        # רוטציה בבאקט רק אחרי העלאה מוצלחת - אותו נימוק כמו מקומית:
        # לא מוחקים עותקים ישנים כשלא הצלחנו ליצור חדש.
        if r2_uploaded:
            try:
                deleted_keys = await rotate_r2_backups(settings.backup_r2_retention_days)
                if deleted_keys:
                    logger.info(
                        "נמחקו %d גיבויים ישנים מ-R2: %s", len(deleted_keys), deleted_keys
                    )
            except Exception:  # noqa: BLE001
                logger.exception("שגיאה ברוטציית גיבויים ב-R2")

    # נמדד בסוף ולא אחרי כתיבת ה-zip, כדי שההעלאה ל-R2 תיכלל במשך הריצה
    duration = asyncio.get_event_loop().time() - started_monotonic

    result = BackupResult(
        success=True,
        filename=filename,
        size_bytes=size_bytes,
        duration_seconds=duration,
        finished_at=datetime.now(timezone.utc),
        collections_count=collections_count,
        documents_count=documents_count,
        r2_enabled=r2_enabled,
        r2_uploaded=r2_uploaded,
        r2_key=r2_key,
        r2_error=r2_error,
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
