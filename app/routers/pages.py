"""ראוטר לדפים הראשיים של האפליקציה"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.core.auth import is_authenticated

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


@router.get("/health")
async def health_check():
    """בדיקת תקינות לשירות (Render משתמש בזה)"""
    return {"status": "ok"}
