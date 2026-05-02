"""
מנגנון הזדהות פשוט:
- סיסמה אחת ממשתנה סביבה
- session cookie חתום (signed) באמצעות itsdangerous
- תוקף 30 ימים
"""
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException, status
from fastapi.responses import RedirectResponse
from app.core.config import get_settings

SESSION_COOKIE_NAME = "taskflow_session"


def get_serializer() -> URLSafeTimedSerializer:
    """יוצר serializer להצפנת ה-session"""
    settings = get_settings()
    return URLSafeTimedSerializer(settings.session_secret, salt="taskflow-session")


def create_session_token() -> str:
    """יוצר token חדש לאחר התחברות מוצלחת"""
    serializer = get_serializer()
    return serializer.dumps({"authenticated": True})


def verify_session_token(token: str) -> bool:
    """בודק אם ה-token תקף ולא פג תוקפו"""
    if not token:
        return False

    settings = get_settings()
    serializer = get_serializer()
    max_age_seconds = settings.session_max_age_days * 24 * 60 * 60

    try:
        data = serializer.loads(token, max_age=max_age_seconds)
        return data.get("authenticated") is True
    except (BadSignature, SignatureExpired):
        return False


def is_authenticated(request: Request) -> bool:
    """בודק אם המשתמש מחובר על פי ה-cookie"""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return verify_session_token(token) if token else False


async def require_auth(request: Request):
    """
    Dependency של FastAPI - דורש שהמשתמש יהיה מחובר.
    אם לא - מחזיר redirect לדף הלוגין.
    משתמש ב-HTTPException מיוחד כי FastAPI לא מאפשר return של response מ-dependency
    """
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"},
        )
    return True


def verify_password(password: str) -> bool:
    """בודק אם הסיסמה תואמת לסיסמה שב-env"""
    settings = get_settings()
    return password == settings.app_password
