"""מודל פתק/טיוטה של השותף (לוח mriox).

Collection נפרד partner_notes - לרעיונות וטיוטות שעדיין אין להם משימה.
מבודד משאר TaskFlow. ראו docs/taskflow-partner-spec.md.
"""
from typing import Optional

from pydantic import BaseModel, Field

from app.models.base import MongoBaseModel


class PartnerNoteBase(BaseModel):
    content: str = Field(..., min_length=1, max_length=20000)  # תוכן (Markdown)


class PartnerNoteCreate(PartnerNoteBase):
    pass


class PartnerNoteUpdate(BaseModel):
    content: Optional[str] = Field(default=None, min_length=1, max_length=20000)


class PartnerNote(MongoBaseModel, PartnerNoteBase):
    content_html: Optional[str] = None  # רינדור Markdown (תוצרת שרת, מסונן)
