"""מודל תגית"""
from typing import Optional
from pydantic import BaseModel, Field
from app.models.base import MongoBaseModel


class TagBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    color: str = Field(default="#3B82F6", pattern=r"^#[0-9A-Fa-f]{6}$")


class TagCreate(TagBase):
    pass


class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class Tag(MongoBaseModel, TagBase):
    usage_count: int = 0


class TagWithUsage(Tag):
    """תגית עם מידע על שימוש - לעמוד הניהול"""
    tasks_count: int = 0
    projects_count: int = 0
