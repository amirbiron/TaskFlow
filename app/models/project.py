"""מודל פרויקט"""
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field
from app.models.base import MongoBaseModel, PyObjectId


class ProjectStatus(str, Enum):
    ACTIVE = "active"  # פעיל
    PENDING = "pending"  # בהמתנה
    COMPLETED = "completed"  # הושלם
    ARCHIVED = "archived"  # בארכיון


class TagDetail(BaseModel):
    """פרטי תגית שמוחזרים בתוך פרויקט/משימה לתצוגה ויזואלית"""
    id: str = Field(alias="_id")
    name: str
    color: str = "#3B82F6"

    model_config = {"populate_by_name": True}


class ProjectLink(BaseModel):
    """קישור בעל שם המוטמע בפרויקט"""
    title: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=1, max_length=2000, pattern=r"^https?://.+")


class ProjectBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    client_id: Optional[str] = None
    status: ProjectStatus = ProjectStatus.ACTIVE
    tags: List[str] = Field(default_factory=list)
    links: List[ProjectLink] = Field(default_factory=list)
    pinned: bool = False  # נעוץ בסיידבר הקיצורים (טאבלט/דסקטופ)


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    client_id: Optional[str] = None
    status: Optional[ProjectStatus] = None
    tags: Optional[List[str]] = None
    links: Optional[List[ProjectLink]] = None
    pinned: Optional[bool] = None


class Project(MongoBaseModel, ProjectBase):
    pass


class ProjectWithStats(Project):
    """פרויקט עם נתונים נלווים - לתצוגות רשימה"""
    open_tasks_count: int = 0
    completed_tasks_count: int = 0
    client_name: Optional[str] = None
    client_color: Optional[str] = None
    tag_details: List[TagDetail] = Field(default_factory=list)
