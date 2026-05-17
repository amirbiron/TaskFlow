"""מודל קובץ מצורף"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from app.models.base import MongoBaseModel, PyObjectId


class AttachmentBase(BaseModel):
    # task_id אופציונלי: תמונות שמשובצות בעורך Markdown (תיאור/מסמך) לא משויכות
    # למשימה ספציפית. רק קבצים שהועלו לאזור "קבצים מצורפים" נושאים task_id.
    task_id: Optional[PyObjectId] = None
    filename: str
    file_url: str
    file_size: int
    mime_type: str


class AttachmentCreate(AttachmentBase):
    pass


class Attachment(MongoBaseModel, AttachmentBase):
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
