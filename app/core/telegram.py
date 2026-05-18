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
    """האם שליחה לטלגרם מאופשרת ומוגדרת תקין."""
    settings = get_settings()
    if not settings.telegram_enabled:
        return False
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


async def send_message(
    text: str,
    *,
    parse_mode: Optional[str] = "HTML",
    disable_web_page_preview: bool = True,
) -> bool:
    """שולח הודעת טקסט לצ'אט המוגדר.

    מחזיר True בהצלחה, False בכישלון / כשהמודול מושבת.
    לא זורק חריגות - השליחה לא קריטית לזרימת האפליקציה.
    """
    if not is_enabled():
        return False

    settings = get_settings()
    url = f"{_TELEGRAM_API_BASE}/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_chat_id,
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
