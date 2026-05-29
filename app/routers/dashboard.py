"""ראוטר לסטטיסטיקות הדשבורד - API"""
from fastapi import APIRouter, Request
from app.core.database import get_database
from app.core.auth import require_api_auth
from app.routers.partner import PARTNER_META_ID

router = APIRouter()


@router.get("/stats")
async def dashboard_stats(request: Request):
    """החזרת סטטיסטיקות מצרפיות לדשבורד"""
    require_api_auth(request)
    db = get_database()

    open_tasks = await db.tasks.count_documents({
        "status": {"$in": ["open", "in_progress"]},
        "archived": {"$ne": True},
    })
    urgent_tasks = await db.tasks.count_documents({
        "status": {"$in": ["open", "in_progress"]},
        "priority": "urgent",
        "archived": {"$ne": True},
    })

    # סימון פעילות שותף שלא נצפתה (מאז שאמיר פתח לאחרונה את לוח השותף)
    partner_unseen = 0
    partner_last_action = None
    meta = await db.partner_meta.find_one({"_id": PARTNER_META_ID})
    if meta:
        partner_unseen = int(meta.get("unseen_count") or 0)
        partner_last_action = meta.get("last_action")

    return {
        "open_tasks": open_tasks,
        "urgent_tasks": urgent_tasks,
        "partner_unseen": partner_unseen,
        "partner_last_action": partner_last_action,
    }
