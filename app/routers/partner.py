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
from zoneinfo import ZoneInfo

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.auth import is_authenticated, require_api_auth
from app.core.config import get_settings
from app.core.database import get_database
from app.models.partner_task import PartnerTaskCreate, PartnerTaskUpdate

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)


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
        "is_done": bool(doc.get("is_done")),
        "last_reminded_date": doc.get("last_reminded_date"),
        "created_at": doc.get("created_at"),
        "stuck_days": _stuck_days(doc.get("created_at")),
    }


# ---------- מסך ציבורי לשותף (ללא לוגין) ----------

@router.get("/m/{secret}", response_class=HTMLResponse)
async def partner_board(request: Request, secret: str):
    """מסך השותף - רק המשימות הפתוחות, ממוינות לפי דדליין (הקרוב למעלה)."""
    _verify_secret_or_404(secret)
    db = get_database()

    raw = await db.partner_tasks.find({"is_done": {"$ne": True}}).to_list(length=1000)

    tasks = []
    for t in raw:
        days = _stuck_days(t.get("created_at"))
        deadline = t.get("deadline")
        tasks.append({
            "id": str(t["_id"]),
            "title": t.get("title") or "",
            "deadline": deadline,
            "deadline_display": deadline.strftime("%d/%m/%Y") if isinstance(deadline, datetime) else "",
            "consequence": (t.get("consequence") or "").strip(),
            "stuck_days": days,
            "stuck_level": _stuck_level(days),
        })

    # מיון לפי דדליין עולה. משימות בלי דדליין יורדות לסוף. מסירים tzinfo
    # כדי להימנע מהשוואת naive מול aware.
    def _key(item):
        d = item["deadline"]
        if isinstance(d, datetime):
            return (0, d.replace(tzinfo=None))
        return (1, datetime.max)

    tasks.sort(key=_key)

    return templates.TemplateResponse(
        "partner_board.html",
        {"request": request, "secret": secret, "tasks": tasks},
    )


@router.post("/m/{secret}/done/{task_id}")
async def partner_mark_done(request: Request, secret: str, task_id: str):
    """סימון משימה כ'סיימתי' מהמסך הציבורי -> יורדת מהרשימה."""
    _verify_secret_or_404(secret)
    obj_id = _validate_object_id(task_id)
    db = get_database()
    await db.partner_tasks.update_one(
        {"_id": obj_id},
        {"$set": {"is_done": True, "updated_at": datetime.utcnow()}},
    )
    # PRG: redirect (303) חזרה ללוח כדי שרענון לא ישלח שוב POST.
    return RedirectResponse(
        url=f"/m/{secret}", status_code=status.HTTP_303_SEE_OTHER
    )


# ---------- ניהול לאמיר (מאחורי הלוגין הקיים) ----------

@router.get("/partner-admin", response_class=HTMLResponse)
async def partner_admin_page(request: Request):
    """דף ניהול לוח השותף."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=302)
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
