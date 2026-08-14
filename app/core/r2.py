"""שכבת אינטגרציה מול Cloudflare R2 (תואם S3) להעלאה והורדה של קבצים."""
from __future__ import annotations
import re
import uuid
from datetime import datetime
from functools import lru_cache
from typing import Optional

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings


# קבצים בעלי המרכאות/בלעדיים. שומרים אותיות, ספרות, נקודה, מקף, קו תחתון.
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class R2Error(RuntimeError):
    """כשל בתקשורת עם R2 או בקונפיגורציה."""


def _has_credentials(settings) -> bool:
    """כל מה שנדרש כדי לפתוח לקוח מול R2 - בלי קשר לבאקט מסוים."""
    return all([
        settings.r2_account_id,
        settings.r2_access_key_id,
        settings.r2_secret_access_key,
    ])


def _is_configured(settings) -> bool:
    """קונפיגורציה מלאה למסירה ציבורית (קבצים מצורפים) - כולל public_url.

    מופרד מ-_has_credentials כי גיבויים נכתבים לבאקט פרטי שאין לו URL
    ציבורי, ולכן אסור שהיעדר public_url יחסום את פתיחת הלקוח.
    """
    return (
        _has_credentials(settings)
        and bool(settings.r2_bucket_name)
        and bool(settings.r2_public_url)
    )


def _resolve_bucket(bucket: Optional[str] = None) -> str:
    """שם הבאקט לפעולה - מפורש, או ברירת המחדל של הקבצים המצורפים."""
    name = bucket or get_settings().r2_bucket_name
    if not name:
        raise R2Error("לא הוגדר שם באקט ב-R2")
    return name


@lru_cache(maxsize=1)
def _get_client():
    settings = get_settings()
    if not _has_credentials(settings):
        raise R2Error("R2 אינו מוגדר - חסרים משתני סביבה")
    endpoint = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        # R2 דורש signature v4 ו-region 'auto'.
        config=Config(signature_version="s3v4", region_name="auto"),
    )


def safe_filename(filename: str) -> str:
    """ניקוי שם קובץ - שמירת סיומת, החלפת תווים לא חוקיים בקו תחתון."""
    name = (filename or "file").strip().replace("\\", "/").split("/")[-1]
    if not name:
        name = "file"
    # פיצול לשם + סיומת לפי הנקודה האחרונה
    if "." in name:
        base, ext = name.rsplit(".", 1)
        ext = "." + _SAFE_FILENAME_RE.sub("_", ext).lower()
    else:
        base, ext = name, ""
    base = _SAFE_FILENAME_RE.sub("_", base).strip("._-") or "file"
    # מגביל אורך כדי שה-key הסופי לא יחרוג מ-1024 בייטים
    return (base[:80] + ext)[:120]


def build_object_key(filename: str, prefix: str = "attachments") -> str:
    """key ייחודי תחת prefix/yyyy/mm/dd/<uuid>-<safe-name>."""
    now = datetime.utcnow()
    date_part = now.strftime("%Y/%m/%d")
    unique = uuid.uuid4().hex[:12]
    name = safe_filename(filename)
    return f"{prefix}/{date_part}/{unique}-{name}"


def public_url_for(key: str) -> str:
    settings = get_settings()
    base = settings.r2_public_url.rstrip("/")
    return f"{base}/{key.lstrip('/')}"


def _upload_bytes_sync(
    data: bytes,
    key: str,
    content_type: str,
    original_filename: Optional[str] = None,
) -> str:
    settings = get_settings()
    # הפונקציה מחזירה URL ציבורי, ולכן דורשת קונפיגורציה מלאה ולא רק אישורי
    # גישה. בלי הבדיקה הזאת היינו מעלים בהצלחה ומחזירים URL שבור.
    if not _is_configured(settings):
        raise R2Error("R2 אינו מוגדר - חסרים משתני סביבה")
    try:
        client = _get_client()
        extra = {
            "ContentType": content_type or "application/octet-stream",
        }
        if original_filename:
            # Content-Disposition נשמר על האובייקט; הדפדפן יעדיף את שם
            # הקובץ המקורי בעת הורדה גם שה-key הסופי מכיל uuid.
            extra["ContentDisposition"] = (
                f'inline; filename="{safe_filename(original_filename)}"'
            )
        client.put_object(
            Bucket=settings.r2_bucket_name,
            Key=key,
            Body=data,
            **extra,
        )
    except (BotoCoreError, ClientError) as exc:
        raise R2Error(f"העלאה ל-R2 נכשלה: {exc}") from exc
    return public_url_for(key)


def _delete_object_sync(key: str, bucket: Optional[str] = None) -> None:
    try:
        client = _get_client()
        client.delete_object(Bucket=_resolve_bucket(bucket), Key=key)
    except (BotoCoreError, ClientError) as exc:
        raise R2Error(f"מחיקה מ-R2 נכשלה: {exc}") from exc


def _upload_file_sync(
    path: str,
    key: str,
    bucket: Optional[str] = None,
    content_type: str = "application/octet-stream",
) -> str:
    """העלאת קובץ מהדיסק. boto3 קורא אותו ב-chunks ועובר ל-multipart לבד,
    כך שקובץ גדול לא נטען כולו לזיכרון."""
    try:
        client = _get_client()
        client.upload_file(
            Filename=path,
            Bucket=_resolve_bucket(bucket),
            Key=key,
            ExtraArgs={"ContentType": content_type or "application/octet-stream"},
        )
    except (BotoCoreError, ClientError, OSError) as exc:
        raise R2Error(f"העלאה ל-R2 נכשלה: {exc}") from exc
    return key


def _list_objects_sync(prefix: str, bucket: Optional[str] = None) -> list[dict]:
    """רשימת אובייקטים תחת prefix. מחזיר key/size/last_modified לכל אחד.
    משתמש ב-paginator כי list_objects_v2 מחזיר עד 1000 אובייקטים בקריאה."""
    try:
        client = _get_client()
        bucket_name = _resolve_bucket(bucket)
        items: list[dict] = []
        for page in client.get_paginator("list_objects_v2").paginate(
            Bucket=bucket_name, Prefix=prefix
        ):
            for obj in page.get("Contents", []):
                items.append({
                    "key": obj["Key"],
                    "size": obj.get("Size", 0),
                    # boto3 מחזיר datetime עם timezone (UTC)
                    "last_modified": obj.get("LastModified"),
                })
        return items
    except (BotoCoreError, ClientError) as exc:
        raise R2Error(f"קריאת רשימת אובייקטים מ-R2 נכשלה: {exc}") from exc


# קריאות boto3 הן blocking I/O. עוטפים ב-run_in_threadpool כדי לא לחנוק
# את ה-event loop של FastAPI בזמן העלאה/מחיקה מ-R2.
async def upload_bytes(
    data: bytes,
    key: str,
    content_type: str,
    original_filename: Optional[str] = None,
) -> str:
    """מעלה bytes ל-R2 (async wrapper) ומחזיר את ה-URL הציבורי."""
    return await run_in_threadpool(
        _upload_bytes_sync, data, key, content_type, original_filename
    )


async def delete_object(key: str, bucket: Optional[str] = None) -> None:
    """מחיקת אובייקט מ-R2 (async wrapper)."""
    await run_in_threadpool(_delete_object_sync, key, bucket)


async def upload_file(
    path: str,
    key: str,
    bucket: Optional[str] = None,
    content_type: str = "application/octet-stream",
) -> str:
    """העלאת קובץ מהדיסק ל-R2 (async wrapper). מחזיר את ה-key."""
    return await run_in_threadpool(_upload_file_sync, path, key, bucket, content_type)


async def list_objects(prefix: str, bucket: Optional[str] = None) -> list[dict]:
    """רשימת אובייקטים תחת prefix (async wrapper)."""
    return await run_in_threadpool(_list_objects_sync, prefix, bucket)


def key_from_public_url(url: str) -> Optional[str]:
    """חילוץ ה-key מתוך URL ציבורי. None אם לא תואם את ה-prefix המוגדר."""
    if not url:
        return None
    settings = get_settings()
    base = (settings.r2_public_url or "").rstrip("/")
    if not base or not url.startswith(base + "/"):
        return None
    return url[len(base) + 1:]
