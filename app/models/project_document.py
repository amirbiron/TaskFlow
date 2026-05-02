"""מודל מסמך-פרויקט (Markdown)."""
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from app.models.base import MongoBaseModel


# מגבלת תוכן: 5MB טקסט (תיעוד יכול להיות ארוך)
MAX_DOCUMENT_CONTENT = 5_000_000


def _normalize_title(v: Optional[str]) -> Optional[str]:
    """trim + ולידציה שהמחרוזת לא ריקה (מונע כותרת של רווחים בלבד)."""
    if v is None:
        return v
    stripped = v.strip()
    if not stripped:
        raise ValueError("title cannot be empty or whitespace only")
    return stripped


class ProjectDocumentBase(BaseModel):
    project_id: str
    title: str = Field(..., min_length=1, max_length=200)
    content_md: str = Field(default="", max_length=MAX_DOCUMENT_CONTENT)


class ProjectDocumentCreate(BaseModel):
    """יצירת מסמך - project_id מגיע מה-URL."""
    title: str = Field(..., min_length=1, max_length=200)
    content_md: str = Field(default="", max_length=MAX_DOCUMENT_CONTENT)

    _normalize_title = field_validator("title")(lambda cls, v: _normalize_title(v))


class ProjectDocumentUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    content_md: Optional[str] = Field(default=None, max_length=MAX_DOCUMENT_CONTENT)

    _normalize_title = field_validator("title")(lambda cls, v: _normalize_title(v))


class ProjectDocument(MongoBaseModel, ProjectDocumentBase):
    """מסמך פרויקט מלא, כולל התוכן."""
    pass


class ProjectDocumentSummary(BaseModel):
    """סיכום לרשימה - בלי תוכן, כדי לחסוך פס רוחב."""
    id: str = Field(alias="_id")
    project_id: str
    title: str
    created_at: str
    updated_at: str

    class Config:
        populate_by_name = True


class ProjectDocumentWithHtml(ProjectDocument):
    """מסמך מלא עם HTML מרונדר."""
    content_html: Optional[str] = None
