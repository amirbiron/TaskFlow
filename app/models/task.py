"""מודל משימה"""
from typing import Optional, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from app.models.base import MongoBaseModel
from app.models.project import TagDetail


class TaskStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class Subtask(BaseModel):
    """תת-משימה - פשוטה, נשמרת בתוך מסמך המשימה"""
    id: str  # UUID יוצר ב-frontend
    title: str = Field(..., min_length=1, max_length=300)
    completed: bool = False


class TaskBase(BaseModel):
    project_id: str
    client_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    title: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.OPEN
    priority: TaskPriority = TaskPriority.NORMAL
    due_date: Optional[datetime] = None
    reminder_date: Optional[datetime] = None
    reminder_sent: bool = False
    tags: List[str] = Field(default_factory=list)  # רשימת tag IDs
    links: List[str] = Field(default_factory=list)
    subtasks: List[Subtask] = Field(default_factory=list)
    column_order: int = 0


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    project_id: Optional[str] = None
    client_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    due_date: Optional[datetime] = None
    reminder_date: Optional[datetime] = None
    reminder_sent: Optional[bool] = None
    tags: Optional[List[str]] = None
    links: Optional[List[str]] = None
    subtasks: Optional[List[Subtask]] = None
    column_order: Optional[int] = None


class TaskStatusUpdate(BaseModel):
    status: TaskStatus
    column_order: int = 0


class TaskOrderUpdate(BaseModel):
    column_order: int


class Task(MongoBaseModel, TaskBase):
    completed_at: Optional[datetime] = None
    description_html: Optional[str] = None  # רינדור Markdown של description (תוצרת שרת)


class TaskWithContext(Task):
    """משימה עם פרטי פרויקט ולקוח"""
    project_name: Optional[str] = None
    client_name: Optional[str] = None
    client_color: Optional[str] = None
    tag_details: List[TagDetail] = Field(default_factory=list)
    comments_count: int = 0
