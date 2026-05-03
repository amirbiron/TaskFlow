"""ראוטר לסטטיסטיקות הדשבורד - API"""
from fastapi import APIRouter, Request
from app.core.database import get_database
from app.core.auth import require_api_auth

router = APIRouter()


@router.get("/stats")
async def dashboard_stats(request: Request):
    """החזרת סטטיסטיקות מצרפיות לדשבורד"""
    require_api_auth(request)
    db = get_database()

    open_tasks = await db.tasks.count_documents({
        "status": {"$in": ["open", "in_progress"]}
    })
    urgent_tasks = await db.tasks.count_documents({
        "status": {"$in": ["open", "in_progress"]},
        "priority": "urgent",
    })

    return {
        "open_tasks": open_tasks,
        "urgent_tasks": urgent_tasks,
    }
