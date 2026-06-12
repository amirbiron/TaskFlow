"""ראוטר לוח משימות השותף (mriox).

תוספת מבודדת ל-TaskFlow. שני חלקים בלבד:
1. מסך ציבורי לשותף ב-/m/<secret> - בלי לוגין, מאומת מול ה-secret שבכתובת.
2. ניהול לאמיר ב-/partner-admin + API תחת /api/partner (מאחורי הלוגין הקיים).

הבידוד מסתמך על סודיות הכתובת (ראו docs/taskflow-partner-spec.md). אם
PARTNER_BOARD_SECRET ריק - המסך הציבורי מחזיר 404 (הפיצ'ר כבוי).
"""
from __future__ import annotations

import logging
import secrets as _secrets
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.core.auth import is_authenticated, require_api_auth
from app.core.config import get_settings
from app.core.database import get_database
from app.core.markdown_renderer import markdown_to_html
from app.core.templating import create_templates
from app.models.partner_task import PartnerTaskCreate, PartnerTaskUpdate
from app.models.partner_note import PartnerNoteCreate, PartnerNoteUpdate

router = APIRouter()
templates = create_templates()
logger = logging.getLogger(__name__)

# מסמך מטא יחיד למעקב פעילות השותף (לסימון בדשבורד של אמיר)
PARTNER_META_ID = "state"


async def _record_partner_activity(db, label: str) -> None:
    """רושם פעולה של השותף לצורך הסימון בדשבורד. לא קריטי - בולע חריגות."""
    try:
        await db.partner_meta.update_one(
            {"_id": PARTNER_META_ID},
            {
                "$inc": {"unseen_count": 1},
                "$set": {"last_activity_at": datetime.utcnow(), "last_action": label},
            },
            upsert=True,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to record partner activity", exc_info=True)


async def _mark_partner_seen(db) -> None:
    """מאפס את מונה הפעילות כשאמיר פותח את מסך הניהול."""
    try:
        await db.partner_meta.update_one(
            {"_id": PARTNER_META_ID},
            {"$set": {"unseen_count": 0, "last_seen_at": datetime.utcnow()}},
            upsert=True,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to mark partner activity seen", exc_info=True)


# ---------- עזרי זמן / בידוד ----------

def _partner_tz() -> ZoneInfo:
    settings = get_settings()
    try:
        return ZoneInfo(settings.partner_timezone)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _stuck_days(created_at: "datetime | None") -> int:
    """מספר הימים מאז יצירת המשימה עד היום, בשעון השותף."""
    if not isinstance(created_at, datetime):
        return 0
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    tz = _partner_tz()
    today = datetime.now(tz).date()
    days = (today - created_at.astimezone(tz).date()).days
    return days if days > 0 else 0


def _stuck_level(days: int) -> str:
    """דירוג חומרה לצביעת מונה-הימים (אדום/בולט ככל שגדל)."""
    if days >= 7:
        return "high"
    if days >= 3:
        return "mid"
    return "low"


def _verify_secret_or_404(secret: str) -> None:
    """מאמת את ה-secret מהכתובת מול ההגדרה. 404 אם כבוי/לא תואם.

    מחזיר 404 (ולא 403) כדי לא לאשר את עצם קיומו של הנתיב.
    """
    configured = (get_settings().partner_board_secret or "").strip()
    if not configured or not _secrets.compare_digest(secret, configured):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _validate_object_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="מזהה לא תקין"
        )


def _serialize_task(doc: dict) -> dict:
    """מבנה אחיד למשימת שותף עבור ה-API, כולל מונה הימים המחושב."""
    return {
        "_id": str(doc["_id"]),
        "title": doc.get("title") or "",
        "deadline": doc.get("deadline"),
        "consequence": doc.get("consequence") or "",
        "reminder_after_days": doc.get("reminder_after_days", 0),
        "progress_note": doc.get("progress_note") or "",
        "is_done": bool(doc.get("is_done")),
        "last_reminded_date": doc.get("last_reminded_date"),
        "created_at": doc.get("created_at"),
        "stuck_days": _stuck_days(doc.get("created_at")),
    }


def _board_task(doc: dict) -> dict:
    """מבנה משימה לתצוגת המסך הציבורי (מונה ימים, רמת חומרה, הערת התקדמות)."""
    days = _stuck_days(doc.get("created_at"))
    return {
        "_id": str(doc["_id"]),
        "title": doc.get("title") or "",
        "deadline": doc.get("deadline"),
        "consequence": (doc.get("consequence") or "").strip(),
        "progress_note": doc.get("progress_note") or "",
        "stuck_days": days,
        "stuck_level": _stuck_level(days),
    }


def _render_note_html(content: str) -> "str | None":
    """רינדור Markdown של פתק ל-HTML מסונן (אותו מנוע של שאר TaskFlow)."""
    if not content or not content.strip():
        return None
    html, _ = markdown_to_html(content, clickable_tasks=False)
    return html


def _serialize_note(doc: dict) -> dict:
    return {
        "_id": str(doc["_id"]),
        "content": doc.get("content") or "",
        "content_html": doc.get("content_html"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


# מודלים לבקשות מהמסך הציבורי (מאומתות מול ה-secret, לא מול לוגין)
class BoardTaskCreate(BaseModel):
    """יצירת משימה ע\"י השותף - בלי consequence (אותו רק אמיר קובע)."""
    title: str = Field(..., min_length=1, max_length=300)
    deadline: Optional[datetime] = None
    reminder_after_days: int = Field(default=3, ge=0, le=3650)


class BoardTaskPatch(BaseModel):
    progress_note: Optional[str] = Field(default=None, max_length=2000)
    is_done: Optional[bool] = None


# ---------- מסך ציבורי לשותף (ללא לוגין) ----------

@router.get("/m/{secret}", response_class=HTMLResponse)
async def partner_board(request: Request, secret: str):
    """מסך השותף - shell של אפליקציית Alpine. הנתונים נטענים דרך ה-API הציבורי."""
    _verify_secret_or_404(secret)
    return templates.TemplateResponse(
        "partner_board.html",
        {"request": request, "secret": secret},
    )


# ---------- ניהול לאמיר (מאחורי הלוגין הקיים) ----------

@router.get("/partner-admin", response_class=HTMLResponse)
async def partner_admin_page(request: Request):
    """דף ניהול לוח השותף."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=302)
    # אמיר פתח את הלוח - מאפסים את סימון הפעילות בדשבורד
    await _mark_partner_seen(get_database())
    settings = get_settings()
    secret = (settings.partner_board_secret or "").strip()
    return templates.TemplateResponse(
        "partner_admin.html",
        {
            "request": request,
            "current_page": "partner",
            "board_url": f"/m/{secret}" if secret else "",
            "partner_telegram_configured": bool(settings.partner_telegram_chat_id),
        },
    )


@router.get("/api/partner/tasks")
async def list_partner_tasks(request: Request):
    """רשימת כל משימות השותף (פתוחות וסגורות) לדף הניהול."""
    require_api_auth(request)
    db = get_database()
    docs = await db.partner_tasks.find().sort(
        [("is_done", 1), ("deadline", 1)]
    ).to_list(length=1000)
    return [_serialize_task(d) for d in docs]


@router.post("/api/partner/tasks", status_code=status.HTTP_201_CREATED)
async def create_partner_task(request: Request, data: PartnerTaskCreate):
    """יצירת משימת שותף חדשה."""
    require_api_auth(request)
    db = get_database()
    now = datetime.utcnow()
    doc = data.model_dump()
    doc["is_done"] = False
    doc["last_reminded_date"] = None
    doc["created_at"] = now
    doc["updated_at"] = now
    result = await db.partner_tasks.insert_one(doc)
    doc["_id"] = result.inserted_id
    return _serialize_task(doc)


@router.put("/api/partner/tasks/{task_id}")
async def update_partner_task(request: Request, task_id: str, data: PartnerTaskUpdate):
    """עדכון משימת שותף (כולל סימון פתוח/סגור)."""
    require_api_auth(request)
    obj_id = _validate_object_id(task_id)
    db = get_database()

    update_doc = data.model_dump(exclude_unset=True)
    if not update_doc:
        existing = await db.partner_tasks.find_one({"_id": obj_id})
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="משימה לא נמצאה"
            )
        return _serialize_task(existing)

    update_doc["updated_at"] = datetime.utcnow()
    result = await db.partner_tasks.find_one_and_update(
        {"_id": obj_id}, {"$set": update_doc}, return_document=True
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="משימה לא נמצאה"
        )
    return _serialize_task(result)


@router.delete("/api/partner/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_partner_task(request: Request, task_id: str):
    """מחיקת משימת שותף."""
    require_api_auth(request)
    obj_id = _validate_object_id(task_id)
    db = get_database()
    result = await db.partner_tasks.delete_one({"_id": obj_id})
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="משימה לא נמצאה"
        )
    return None


# ---------- API ציבורי למסך השותף (מאומת מול ה-secret, ללא לוגין) ----------

@router.get("/api/partner/board/{secret}/tasks")
async def board_list_tasks(request: Request, secret: str):
    """המשימות הפתוחות של השותף, ממוינות לפי דדליין (הקרוב למעלה)."""
    _verify_secret_or_404(secret)
    db = get_database()
    raw = await db.partner_tasks.find({"is_done": {"$ne": True}}).to_list(length=1000)

    def _key(d):
        dl = d.get("deadline")
        if isinstance(dl, datetime):
            return (0, dl.replace(tzinfo=None))
        return (1, datetime.max)

    raw.sort(key=_key)
    return [_board_task(d) for d in raw]


@router.post("/api/partner/board/{secret}/tasks", status_code=status.HTTP_201_CREATED)
async def board_create_task(request: Request, secret: str, data: BoardTaskCreate):
    """הוספת משימה ע\"י השותף - title/deadline/reminder_after_days בלבד."""
    _verify_secret_or_404(secret)
    db = get_database()
    now = datetime.utcnow()
    doc = {
        "title": data.title,
        "deadline": data.deadline,
        "consequence": "",  # רק אמיר קובע consequence (ממסך הניהול)
        "reminder_after_days": data.reminder_after_days,
        "progress_note": "",
        "is_done": False,
        "last_reminded_date": None,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.partner_tasks.insert_one(doc)
    doc["_id"] = result.inserted_id
    await _record_partner_activity(db, "הוספת משימה")
    return _board_task(doc)


@router.patch("/api/partner/board/{secret}/tasks/{task_id}")
async def board_patch_task(request: Request, secret: str, task_id: str, data: BoardTaskPatch):
    """עדכון הערת התקדמות ו/או סימון 'סיימתי' מהמסך הציבורי."""
    _verify_secret_or_404(secret)
    obj_id = _validate_object_id(task_id)
    db = get_database()

    update_doc = data.model_dump(exclude_unset=True)
    if not update_doc:
        existing = await db.partner_tasks.find_one({"_id": obj_id})
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="משימה לא נמצאה"
            )
        return _board_task(existing)

    update_doc["updated_at"] = datetime.utcnow()
    result = await db.partner_tasks.find_one_and_update(
        {"_id": obj_id}, {"$set": update_doc}, return_document=True
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="משימה לא נמצאה"
        )
    if update_doc.get("is_done") is True:
        await _record_partner_activity(db, "סימון משימה כבוצעה")
    elif "progress_note" in update_doc:
        await _record_partner_activity(db, "עדכון התקדמות")
    return _board_task(result)


@router.get("/api/partner/board/{secret}/notes")
async def board_list_notes(request: Request, secret: str):
    """רשימת הפתקים/טיוטות של השותף, מהעדכני לישן."""
    _verify_secret_or_404(secret)
    db = get_database()
    docs = await db.partner_notes.find().sort("updated_at", -1).to_list(length=1000)
    return [_serialize_note(d) for d in docs]


@router.post("/api/partner/board/{secret}/notes", status_code=status.HTTP_201_CREATED)
async def board_create_note(request: Request, secret: str, data: PartnerNoteCreate):
    """יצירת פתק/טיוטה חדש."""
    _verify_secret_or_404(secret)
    db = get_database()
    now = datetime.utcnow()
    doc = {
        "content": data.content,
        "content_html": _render_note_html(data.content),
        "created_at": now,
        "updated_at": now,
    }
    result = await db.partner_notes.insert_one(doc)
    doc["_id"] = result.inserted_id
    await _record_partner_activity(db, "פתק חדש")
    return _serialize_note(doc)


@router.patch("/api/partner/board/{secret}/notes/{note_id}")
async def board_update_note(request: Request, secret: str, note_id: str, data: PartnerNoteUpdate):
    """עריכת פתק קיים."""
    _verify_secret_or_404(secret)
    obj_id = _validate_object_id(note_id)
    db = get_database()

    update_doc = data.model_dump(exclude_unset=True)
    if "content" in update_doc:
        update_doc["content_html"] = _render_note_html(update_doc.get("content") or "")
    if not update_doc:
        existing = await db.partner_notes.find_one({"_id": obj_id})
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="פתק לא נמצא"
            )
        return _serialize_note(existing)

    update_doc["updated_at"] = datetime.utcnow()
    result = await db.partner_notes.find_one_and_update(
        {"_id": obj_id}, {"$set": update_doc}, return_document=True
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="פתק לא נמצא"
        )
    await _record_partner_activity(db, "עריכת פתק")
    return _serialize_note(result)


@router.delete("/api/partner/board/{secret}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def board_delete_note(request: Request, secret: str, note_id: str):
    """מחיקת פתק."""
    _verify_secret_or_404(secret)
    obj_id = _validate_object_id(note_id)
    db = get_database()
    result = await db.partner_notes.delete_one({"_id": obj_id})
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="פתק לא נמצא"
        )
    await _record_partner_activity(db, "מחיקת פתק")
    return None
