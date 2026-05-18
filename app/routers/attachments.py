"""ראוטר לקבצים מצורפים - העלאה, רשימה ומחיקה."""
import logging
from datetime import datetime
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, status

from app.core.auth import require_api_auth
from app.core.database import get_database
from app.core.db_utils import validate_object_id
from app.core import r2

router = APIRouter()
logger = logging.getLogger(__name__)


# מגבלות גודל (בייטים)
MAX_IMAGE_SIZE = 5 * 1024 * 1024     # 5MB
MAX_FILE_SIZE = 20 * 1024 * 1024     # 20MB

# מיפוי קנוני של סיומת מותרת ל-MIME היחיד שאנחנו שומרים.
# זהו ה-whitelist היחיד - סיומת שאינה כאן נדחית, גם אם הדפדפן הצהיר על
# MIME "תמים" (למשל application/octet-stream על .exe/.html/.bat).
MIME_BY_EXT = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "pdf": "application/pdf",
    "txt": "text/plain",
    "md": "text/markdown",
    "zip": "application/zip",
    "rar": "application/vnd.rar",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}


def _ext_of(filename: Optional[str]) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


async def _read_with_limit(upload: UploadFile, limit: int) -> bytes:
    """קריאת הקובץ עם הגבלת גודל. זורק 413 אם חרג."""
    # קוראים בצ'אנקים כדי שקובץ ענק לא יתפח את הזיכרון לפני הבדיקה.
    chunks: list[bytes] = []
    total = 0
    chunk_size = 1024 * 1024
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"הקובץ גדול מדי (מקסימום {limit // (1024 * 1024)}MB)",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _serialize(doc: dict) -> dict:
    """המרת רשומת attachment לפורמט JSON ידידותי."""
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    for key in ("created_at", "updated_at", "uploaded_at"):
        if out.get(key) and isinstance(out[key], datetime):
            out[key] = out[key].isoformat()
    return out


async def _ensure_task_exists(db, task_id: str) -> ObjectId:
    obj_id = validate_object_id(task_id)
    task = await db.tasks.find_one({"_id": obj_id}, {"_id": 1})
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="משימה לא נמצאה",
        )
    return obj_id


@router.post("/uploads/image", status_code=status.HTTP_201_CREATED)
async def upload_image(request: Request, file: UploadFile = File(...)):
    """העלאת תמונה לעורך Markdown (תיאור משימה / מסמך פרויקט).

    אינה משויכת למשימה - השיבוץ עצמו ב-Markdown הוא הקישור היחיד.
    """
    require_api_auth(request)

    ext = _ext_of(file.filename)
    raw_mime = (file.content_type or "").lower()
    if raw_mime == "image/jpg":
        raw_mime = "image/jpeg"

    # אכיפה: הסיומת חייבת להיות במפה הקנונית ולהיות סיומת תמונה.
    # אם ה-MIME שהדפדפן הצהיר עליו ידוע, הוא חייב להתאים לקנוני
    # (octet-stream מותר כי דפדפנים שולחים זאת לסיומות לא מזוהות).
    canonical = MIME_BY_EXT.get(ext)
    if not canonical or ext not in IMAGE_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ניתן להעלות רק תמונות (png/jpg/gif/webp)",
        )
    if raw_mime and raw_mime != canonical and raw_mime != "application/octet-stream":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ניתן להעלות רק תמונות (png/jpg/gif/webp)",
        )
    mime = canonical

    data = await _read_with_limit(file, MAX_IMAGE_SIZE)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="הקובץ ריק",
        )

    key = r2.build_object_key(file.filename or f"image.{ext or 'png'}")
    try:
        url = await r2.upload_bytes(data, key, mime, original_filename=file.filename)
    except r2.R2Error as exc:
        logger.exception("R2 image upload failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )

    db = get_database()
    now = datetime.utcnow()
    doc = {
        "task_id": None,
        "filename": file.filename or "image",
        "file_url": url,
        "file_size": len(data),
        "mime_type": mime,
        "uploaded_at": now,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.attachments.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize(doc)


@router.get("/tasks/{task_id}/attachments")
async def list_task_attachments(request: Request, task_id: str):
    """רשימת קבצים מצורפים של משימה."""
    require_api_auth(request)
    db = get_database()
    await _ensure_task_exists(db, task_id)

    cursor = db.attachments.find({"task_id": task_id}).sort("uploaded_at", -1)
    docs = await cursor.to_list(length=500)
    return [_serialize(d) for d in docs]


@router.post("/tasks/{task_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_task_attachment(
    request: Request, task_id: str, file: UploadFile = File(...),
):
    """העלאת קובץ ושיוכו למשימה."""
    require_api_auth(request)
    db = get_database()
    await _ensure_task_exists(db, task_id)

    ext = _ext_of(file.filename)
    raw_mime = (file.content_type or "").lower()
    if raw_mime == "image/jpg":
        raw_mime = "image/jpeg"

    # אכיפה: MIME_BY_EXT הוא ה-whitelist היחיד. סיומת שאינה שם נדחית,
    # גם אם ה-MIME מ-content_type נראה תמים (למשל application/octet-stream
    # על .exe/.html/.bat - הדפדפן שולח את זה לסיומות לא מזוהות).
    # אם הסיומת מוכרת - ה-MIME חייב להתאים לקנוני או להיות octet-stream.
    canonical = MIME_BY_EXT.get(ext)
    if not canonical:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="סוג קובץ לא נתמך",
        )
    if raw_mime and raw_mime != canonical and raw_mime != "application/octet-stream":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="סוג קובץ לא נתמך",
        )
    mime = canonical

    is_image = ext in IMAGE_EXT
    limit = MAX_IMAGE_SIZE if is_image else MAX_FILE_SIZE
    data = await _read_with_limit(file, limit)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="הקובץ ריק",
        )

    key = r2.build_object_key(file.filename or f"file.{ext or 'bin'}")
    try:
        url = await r2.upload_bytes(data, key, mime, original_filename=file.filename)
    except r2.R2Error as exc:
        logger.exception("R2 attachment upload failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )

    now = datetime.utcnow()
    doc = {
        "task_id": task_id,
        "filename": file.filename or "file",
        "file_url": url,
        "file_size": len(data),
        "mime_type": mime,
        "uploaded_at": now,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.attachments.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize(doc)


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(request: Request, attachment_id: str):
    """מחיקת קובץ מצורף (כולל מחיקה מ-R2)."""
    require_api_auth(request)
    db = get_database()
    obj_id = validate_object_id(attachment_id)

    doc = await db.attachments.find_one({"_id": obj_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="קובץ לא נמצא",
        )

    # ניסיון למחוק מ-R2 - אם נכשל לא חוסם את מחיקת ה-DB; עדיף יתום ב-R2
    # על פני רשומה תקועה ב-DB.
    key = r2.key_from_public_url(doc.get("file_url") or "")
    if key:
        try:
            await r2.delete_object(key)
        except r2.R2Error:
            logger.warning("Failed to delete R2 object %s", key, exc_info=True)

    await db.attachments.delete_one({"_id": obj_id})
    return None
