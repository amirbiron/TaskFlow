"""מודל מסמך-פרויקט (Markdown)."""
from typing import Optional
from pydantic import BaseModel, Field
from app.models.base import MongoBaseModel


# מגבלת תוכן: 5MB טקסט (תיעוד יכול להיות ארוך)
MAX_DOCUMENT_CONTENT = 5_000_000


class ProjectDocumentBase(BaseModel):
    project_id: str
    title: str = Field(..., min_length=1, max_length=200)
    content_md: str = Field(default="", max_length=MAX_DOCUMENT_CONTENT)


class ProjectDocumentCreate(BaseModel):
    """יצירת מסמך - project_id מגיע מה-URL."""
    title: str = Field(..., min_length=1, max_length=200)
    content_md: str = Field(default="", max_length=MAX_DOCUMENT_CONTENT)


class ProjectDocumentUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    content_md: Optional[str] = Field(default=None, max_length=MAX_DOCUMENT_CONTENT)


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
