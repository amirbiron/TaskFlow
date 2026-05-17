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

# סוגי תוכן מותרים לתמונות (לעורך Markdown)
ALLOWED_IMAGE_MIME = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
}
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}

# סוגי תוכן מותרים לקבצים מצורפים למשימה (תמונות + מסמכים + ארכיונים)
ALLOWED_DOCUMENT_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # docx
    "application/msword",  # שמרני: לקבצי doc ישנים (לא חובה, יקרה רק אם הדפדפן יזהה ככה)
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",        # xlsx
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # pptx
    "application/vnd.ms-powerpoint",
    "text/plain",
    "text/markdown",
}
ALLOWED_DOCUMENT_EXT = {"pdf", "docx", "xlsx", "pptx", "txt", "md"}

ALLOWED_ARCHIVE_MIME = {
    "application/zip",
    "application/x-zip-compressed",
    "application/x-rar-compressed",
    "application/vnd.rar",
    "application/octet-stream",  # דפדפנים מסוימים שולחים ככה לארכיונים
}
ALLOWED_ARCHIVE_EXT = {"zip", "rar"}

ALLOWED_FILE_MIME = ALLOWED_IMAGE_MIME | ALLOWED_DOCUMENT_MIME | ALLOWED_ARCHIVE_MIME
ALLOWED_FILE_EXT = ALLOWED_IMAGE_EXT | ALLOWED_DOCUMENT_EXT | ALLOWED_ARCHIVE_EXT


def _ext_of(filename: Optional[str]) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def _is_image(mime: str, ext: str) -> bool:
    return mime in ALLOWED_IMAGE_MIME or ext in ALLOWED_IMAGE_EXT


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
    mime = (file.content_type or "").lower()
    if not _is_image(mime, ext):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ניתן להעלות רק תמונות (png/jpg/gif/webp)",
        )

    data = await _read_with_limit(file, MAX_IMAGE_SIZE)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="הקובץ ריק",
        )

    # מיישרים את ה-mime לאחד מהמותרים (חלק מהדפדפנים שולחים image/jpg)
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in ALLOWED_IMAGE_MIME:
        mime = f"image/{ext}" if ext in ALLOWED_IMAGE_EXT else "application/octet-stream"

    key = r2.build_object_key(file.filename or f"image.{ext or 'png'}")
    try:
        url = r2.upload_bytes(data, key, mime, original_filename=file.filename)
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
    mime = (file.content_type or "").lower()

    is_image = _is_image(mime, ext)
    is_allowed = (
        mime in ALLOWED_FILE_MIME
        or ext in ALLOWED_FILE_EXT
    )
    if not is_allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="סוג קובץ לא נתמך",
        )

    # אם זה ארכיון בלבד שמגיע כ-octet-stream - נוודא לפי הסיומת
    if mime == "application/octet-stream" and ext not in ALLOWED_FILE_EXT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="סוג קובץ לא נתמך",
        )

    limit = MAX_IMAGE_SIZE if is_image else MAX_FILE_SIZE
    data = await _read_with_limit(file, limit)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="הקובץ ריק",
        )

    # יישור mime לסטנדרט מותר
    if mime == "image/jpg":
        mime = "image/jpeg"
    if not mime or mime == "application/octet-stream":
        mime_by_ext = {
            "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "webp": "image/webp",
            "pdf": "application/pdf", "txt": "text/plain", "md": "text/markdown",
            "zip": "application/zip", "rar": "application/vnd.rar",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
        mime = mime_by_ext.get(ext, "application/octet-stream")

    key = r2.build_object_key(file.filename or f"file.{ext or 'bin'}")
    try:
        url = r2.upload_bytes(data, key, mime, original_filename=file.filename)
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
            r2.delete_object(key)
        except r2.R2Error:
            logger.warning("Failed to delete R2 object %s", key, exc_info=True)

    await db.attachments.delete_one({"_id": obj_id})
    return None
