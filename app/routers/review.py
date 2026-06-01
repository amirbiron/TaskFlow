"""ראוטר לסקירת משימות (Serendipity Review) - API.

מציג משימה אחת זמינה לסקירה בכל פעם, ומעדכן את הסטטוס שלה יחד עם חותמת "נסקר".
משתמש בערכי הסטטוס הקיימים בלבד (open / in_progress / completed) - בלי סטטוסים חדשים.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from app.core.auth import require_api_auth
from app.core.config import get_settings
from app.core.database import get_database
from app.models.task import TaskStatus
# שימוש חוזר בעזרים של ראוטר המשימות כדי לא לשכפל לוגיקה
from app.routers.tasks import _serialize, _validate_object_id

router = APIRouter()
logger = logging.getLogger(__name__)


class ReviewActionRequest(BaseModel):
    """בחירת סטטוס בסקירה. הערך מוגבל לשלושת ערכי הסטטוס הקיימים."""
    status: TaskStatus


async def _project_name(db, project_id) -> Optional[str]:
    """שליפת שם הפרויקט של המשימה לתצוגה בראש כרטיס הסקירה.

    מחזיר None אם אין project_id, אם המזהה לא תקין, או אם הפרויקט לא נמצא
    (למשל נמחק) - כך שהתצוגה פשוט לא תציג תווית, בלי לשבור את הסקירה.
    שולף את שדה השם בלבד, בדומה לחלק הפרויקט ב-tasks._enrich_task.
    """
    if not project_id:
        return None
    try:
        project = await db.projects.find_one(
            {"_id": ObjectId(project_id)},
            {"name": 1},
        )
    except (InvalidId, TypeError):
        return None
    return project.get("name") if project else None


@router.get("/next")
async def get_next_review_task(
    request: Request,
    exclude: str = Query("", description="מזהי משימות לדילוג (מופרדים בפסיק) - לא יוחזרו"),
):
    """החזרת משימה אקראית אחת הזמינה לסקירה, או null אם אין.

    משימה זמינה לסקירה אם: הסטטוס אינו "הושלם", היא לא בארכיון, והיא לא נסקרה
    ב-X הימים האחרונים (cooldown). משימה שמעולם לא נסקרה (שדה ריק/חסר) - זמינה.

    `exclude` מאפשר לדלג על משימות בסבב הנוכחי (לא יוחזרו) בלי לשנות אותן.
    """
    require_api_auth(request)
    db = get_database()
    settings = get_settings()

    cutoff = datetime.utcnow() - timedelta(days=settings.serendipity_cooldown_days)
    query = {
        "status": {"$ne": TaskStatus.COMPLETED.value},
        "archived": {"$ne": True},
        "$or": [
            # שדה חסר/ריק ב-Mongo תואם ל-None => "מעולם לא נסקרה"
            {"last_reviewed_at": None},
            {"last_reviewed_at": {"$lt": cutoff}},
        ],
    }

    # החרגת משימות שדילגו עליהן בסבב הנוכחי (מזהים לא תקינים פשוט מתעלמים מהם)
    exclude_ids = [ObjectId(x) for x in exclude.split(",") if x and ObjectId.is_valid(x)]
    if exclude_ids:
        query["_id"] = {"$nin": exclude_ids}

    # בחירה אקראית של מסמך אחד מתוך הזמינים
    docs = await db.tasks.aggregate([
        {"$match": query},
        {"$sample": {"size": 1}},
    ]).to_list(length=1)

    if not docs:
        return {"task": None}

    task = _serialize(docs[0])
    # העשרה מינימלית: שם הפרויקט לתצוגה בראש כרטיס הסקירה
    task["project_name"] = await _project_name(db, task.get("project_id"))
    return {"task": task}


@router.post("/{task_id}")
async def submit_review(request: Request, task_id: str, body: ReviewActionRequest):
    """עדכון סטטוס המשימה בסקירה + רישום חותמת זמן "נסקר עכשיו"."""
    require_api_auth(request)
    db = get_database()

    obj_id = _validate_object_id(task_id)
    existing = await db.tasks.find_one({"_id": obj_id})
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="משימה לא נמצאה",
        )

    now = datetime.utcnow()
    update_doc = {
        "status": body.status,
        "last_reviewed_at": now,
        "updated_at": now,
    }

    # שמירה על האינווריאנט של completed_at, עקבי עם שאר עדכוני הסטטוס במערכת
    if body.status == TaskStatus.COMPLETED and existing.get("status") != TaskStatus.COMPLETED:
        update_doc["completed_at"] = now
    elif body.status != TaskStatus.COMPLETED and existing.get("status") == TaskStatus.COMPLETED:
        update_doc["completed_at"] = None

    result = await db.tasks.find_one_and_update(
        {"_id": obj_id},
        {"$set": update_doc},
        return_document=True,
    )
    if not result:
        # המשימה נמחקה בין השליפה לעדכון
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="משימה לא נמצאה",
        )

    return _serialize(result)
