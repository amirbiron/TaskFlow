"""ראוטר לדפים הראשיים של האפליקציה"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.core.auth import is_authenticated
from app.core.markdown_renderer import pygments_css

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _require_auth_or_redirect(request: Request):
    """אם לא מחובר - מחזיר redirect, אחרת None"""
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=302)
    return None


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """דף הבית - דשבורד"""
    redirect = _require_auth_or_redirect(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "current_page": "dashboard"}
    )


@router.get("/clients", response_class=HTMLResponse)
async def clients_page(request: Request):
    """עמוד ניהול לקוחות"""
    redirect = _require_auth_or_redirect(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        "clients.html",
        {"request": request, "current_page": "clients"}
    )


@router.get("/projects", response_class=HTMLResponse)
async def projects_page(request: Request):
    """עמוד ניהול פרויקטים"""
    redirect = _require_auth_or_redirect(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        "projects.html",
        {"request": request, "current_page": "projects"}
    )


@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail_page(request: Request, project_id: str):
    """עמוד פרטי פרויקט בודד"""
    redirect = _require_auth_or_redirect(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        "project_detail.html",
        {
            "request": request,
            "current_page": "projects",
            "project_id": project_id,
            "pygments_css": pygments_css(),
        }
    )


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request):
    """עמוד כל המשימות (תצוגה גלובלית)"""
    redirect = _require_auth_or_redirect(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        "tasks.html",
        {"request": request, "current_page": "tasks"}
    )


@router.get("/tags", response_class=HTMLResponse)
async def tags_page(request: Request):
    """עמוד ניהול תגיות"""
    redirect = _require_auth_or_redirect(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        "tags.html",
        {"request": request, "current_page": "tags"}
    )


@router.get("/health")
async def health_check():
    """בדיקת תקינות לשירות (Render משתמש בזה)"""
    return {"status": "ok"}
