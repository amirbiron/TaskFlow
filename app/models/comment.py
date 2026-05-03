"""מודל הערה (קומנט) על משימה - תוכן ב-Markdown."""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
from app.models.base import MongoBaseModel


# אורך מקסימלי של גוף הערה - מספיק לרוב הצרכים, מונע התנפחות מסמכים
MAX_COMMENT_BODY = 10_000


class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=MAX_COMMENT_BODY)


class CommentUpdate(BaseModel):
    body: str = Field(..., min_length=1, max_length=MAX_COMMENT_BODY)


class TaskCommentBase(BaseModel):
    task_id: str
    body: str
    body_html: str = ""
    edited_at: Optional[datetime] = None


class TaskComment(MongoBaseModel, TaskCommentBase):
    pass
