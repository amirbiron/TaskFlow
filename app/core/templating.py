"""יצירת מופעי Jinja2Templates עם גלובלים משותפים.

המטרה העיקרית: cache-busting ל-CSS/נכסים סטטיים. בלי פרמטר גרסה
דפדפנים ממשיכים להציג CSS מטומן ישן גם אחרי deploy חדש - מה שגורם
לכך ששינויי עיצוב (למשל צבעי בלוקי admonition) לא מופיעים למשתמש.
"""
from __future__ import annotations
import os

from fastapi.templating import Jinja2Templates

# הגרסה מחושבת לפי זמן השינוי של main.css בזמן עליית התהליך. בכל deploy
# הקובץ נכתב מחדש -> mtime משתנה -> הדפדפן מאלץ טעינה מחדש של ה-CSS.
_CSS_PATH = os.path.join("app", "static", "css", "main.css")


def _asset_version() -> str:
    try:
        return str(int(os.path.getmtime(_CSS_PATH)))
    except OSError:
        return ""


def create_templates(directory: str = "app/templates") -> Jinja2Templates:
    """מחזיר Jinja2Templates עם הגלובל asset_version לשימוש ב-cache-busting."""
    templates = Jinja2Templates(directory=directory)
    templates.env.globals["asset_version"] = _asset_version()
    return templates
