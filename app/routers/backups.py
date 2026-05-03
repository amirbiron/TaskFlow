"""
ראוטר לניהול גיבויי MongoDB.

כולל גם דף HTML לניהול וגם API:
- GET  /admin/backups - דף ניהול
- GET  /api/admin/backups - רשימה JSON
- POST /api/admin/backups/run - טריגר ידני לגיבוי
- GET  /api/admin/backups/{filename}/download - הורדת קובץ
- DELETE /api/admin/backups/{filename} - מחיקה ידנית
"""
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.auth import is_authenticated, require_api_auth
from app.core.backup import (
    BACKUP_ALREADY_RUNNING_ERROR,
    delete_backup,
    get_backup_path,
    get_last_result,
    list_backups,
    run_backup,
)
from app.core.config import get_settings
from app.core.scheduler import get_next_run_time

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/admin/backups", response_class=HTMLResponse)
async def backups_page(request: Request):
    """דף ניהול הגיבויים."""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=302)

    settings = get_settings()
    return templates.TemplateResponse(
        "admin_backups.html",
        {
            "request": request,
            "current_page": "backups",
            "backup_enabled": settings.backup_enabled,
            "retention_days": settings.backup_retention_days,
            "backup_hour": settings.backup_hour,
            "backup_minute": settings.backup_minute,
        },
    )


@router.get("/api/admin/backups")
async def api_list_backups(request: Request):
    """רשימת גיבויים + מטא של הריצה האחרונה ושל ה-scheduler."""
    require_api_auth(request)

    backups = list_backups()
    last = get_last_result()
    return {
        "backups": [b.to_dict() for b in backups],
        "last_run": last.to_dict() if last else None,
        "next_run_at": get_next_run_time(),
        "total_size_bytes": sum(b.size_bytes for b in backups),
    }


@router.post("/api/admin/backups/run", status_code=status.HTTP_200_OK)
async def api_run_backup(request: Request):
    """טריגר ידני לגיבוי - חוסם עד לסיום (גיבוי קצר ברוב המקרים)."""
    require_api_auth(request)

    result = await run_backup()
    if not result.success:
        # מבדילים בין "כבר רץ" (409) לכשל אמיתי (500) כדי שה-UI יוכל להתאים
        # את ההודעה. אם תפוס - לא צריך להיכנס לפאניקה, רק לרענן בעוד רגע.
        if result.error == BACKUP_ALREADY_RUNNING_ERROR:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=result.error,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error or "הגיבוי נכשל",
        )
    return result.to_dict()


@router.get("/api/admin/backups/{filename}/download")
async def api_download_backup(request: Request, filename: str):
    """הורדת קובץ גיבוי בודד."""
    require_api_auth(request)

    path = get_backup_path(filename)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="קובץ גיבוי לא נמצא",
        )

    return FileResponse(
        path=path,
        filename=filename,
        media_type="application/gzip",
    )


@router.delete("/api/admin/backups/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def api_delete_backup(request: Request, filename: str):
    """מחיקה ידנית של גיבוי."""
    require_api_auth(request)

    if not delete_backup(filename):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="קובץ גיבוי לא נמצא",
        )
    return None
