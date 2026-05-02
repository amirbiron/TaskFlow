"""ראוטר לסטטיסטיקות הדשבורד - API"""
from fastapi import APIRouter, HTTPException, Request, status
from app.core.database import get_database
from app.core.auth import is_authenticated

router = APIRouter()


def _check_auth(request: Request):
    """בדיקת הזדהות פנימית"""
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="לא מחובר"
        )


@router.get("/stats")
async def dashboard_stats(request: Request):
    """החזרת סטטיסטיקות מצרפיות לדשבורד"""
    _check_auth(request)
    db = get_database()

    open_tasks = await db.tasks.count_documents({
        "status": {"$in": ["open", "in_progress"]}
    })
    urgent_tasks = await db.tasks.count_documents({
        "status": {"$in": ["open", "in_progress"]},
        "priority": "urgent",
    })
    active_projects = await db.projects.count_documents({"status": "active"})
    clients = await db.clients.count_documents({})

    return {
        "open_tasks": open_tasks,
        "urgent_tasks": urgent_tasks,
        "active_projects": active_projects,
        "clients": clients,
    }
