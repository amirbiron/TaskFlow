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


def _is_configured(settings) -> bool:
    return all([
        settings.r2_account_id,
        settings.r2_access_key_id,
        settings.r2_secret_access_key,
        settings.r2_bucket_name,
        settings.r2_public_url,
    ])


@lru_cache(maxsize=1)
def _get_client():
    settings = get_settings()
    if not _is_configured(settings):
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
    try:
        client = _get_client()
        settings = get_settings()
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


def _delete_object_sync(key: str) -> None:
    try:
        client = _get_client()
        settings = get_settings()
        client.delete_object(Bucket=settings.r2_bucket_name, Key=key)
    except (BotoCoreError, ClientError) as exc:
        raise R2Error(f"מחיקה מ-R2 נכשלה: {exc}") from exc


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


async def delete_object(key: str) -> None:
    """מחיקת אובייקט מ-R2 (async wrapper)."""
    await run_in_threadpool(_delete_object_sync, key)


def key_from_public_url(url: str) -> Optional[str]:
    """חילוץ ה-key מתוך URL ציבורי. None אם לא תואם את ה-prefix המוגדר."""
    if not url:
        return None
    settings = get_settings()
    base = (settings.r2_public_url or "").rstrip("/")
    if not base or not url.startswith(base + "/"):
        return None
    return url[len(base) + 1:]
