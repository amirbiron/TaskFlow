"""ראוטר להזדהות - login, logout"""
from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import RedirectResponse, HTMLResponse
from app.core.auth import (
    verify_password,
    create_session_token,
    is_authenticated,
    SESSION_COOKIE_NAME,
)
from app.core.config import get_settings
from app.core.templating import create_templates

router = APIRouter()
templates = create_templates()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """מציג את דף ההתחברות"""
    # אם כבר מחובר - הפנה לדשבורד
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None}
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(...)):
    """מטפל בשליחת טופס ההתחברות"""
    if not verify_password(password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "סיסמה שגויה"},
            status_code=401,
        )

    # יצירת token והפניה לדשבורד
    token = create_session_token()
    settings = get_settings()
    max_age = settings.session_max_age_days * 24 * 60 * 60

    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=not settings.debug,  # ב-production - secure בלבד
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout():
    """התנתקות - מחיקת ה-cookie"""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return response


@router.get("/api/auth/check")
async def check_auth(request: Request):
    """בדיקה אם המשתמש מחובר"""
    return {"authenticated": is_authenticated(request)}
