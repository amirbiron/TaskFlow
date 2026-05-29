"""שליחת הודעות לטלגרם.

שכבת תקשורת דקה מעל Telegram Bot API. הפונקציות מתעלמות בשקט
כאשר Telegram לא מוגדר/מושבת - כדי שמסלולים אחרים באפליקציה
לא ייכשלו רק בגלל בעיית התראה.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TELEGRAM_API_BASE = "https://api.telegram.org"
_REQUEST_TIMEOUT_SECONDS = 10.0


def is_enabled() -> bool:
    """האם שליחה לטלגרם מאופשרת ומוגדרת תקין (צ'אט ברירת המחדל)."""
    settings = get_settings()
    if not settings.telegram_enabled:
        return False
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def partner_is_enabled() -> bool:
    """האם תזכורות לשותף מאופשרות - אותו בוט קיים + chat_id של השותף."""
    settings = get_settings()
    if not settings.telegram_enabled:
        return False
    return bool(settings.telegram_bot_token and settings.partner_telegram_chat_id)


async def send_message(
    text: str,
    *,
    chat_id: Optional[str] = None,
    parse_mode: Optional[str] = "HTML",
    disable_web_page_preview: bool = True,
) -> bool:
    """שולח הודעת טקסט לצ'אט.

    chat_id - יעד אופציונלי. אם לא סופק, נשלח לצ'אט ברירת המחדל
    (settings.telegram_chat_id). מאפשר שימוש חוזר באותו בוט לשליחה
    לצ'אט השותף בלי חיבור/בוט נוסף.

    מחזיר True בהצלחה, False בכישלון / כשהמודול מושבת.
    לא זורק חריגות - השליחה לא קריטית לזרימת האפליקציה.
    """
    settings = get_settings()
    target_chat = chat_id or settings.telegram_chat_id
    # שער כניסה: kill-switch כללי + טוקן + יעד כלשהו. כשמועבר chat_id מפורש
    # אין תלות בצ'אט ברירת המחדל (telegram_chat_id יכול להישאר ריק).
    if not settings.telegram_enabled or not settings.telegram_bot_token or not target_chat:
        return False

    url = f"{_TELEGRAM_API_BASE}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            logger.warning(
                "Telegram sendMessage failed: status=%s body=%s",
                resp.status_code, resp.text[:300],
            )
            return False
        data = resp.json()
        if not data.get("ok"):
            logger.warning("Telegram API returned ok=false: %s", data)
            return False
        return True
    except httpx.HTTPError as exc:
        logger.warning("Telegram HTTP error: %s", exc)
        return False
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error sending Telegram message")
        return False
