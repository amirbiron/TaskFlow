"""מודל משימה"""
from typing import Optional, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field
from app.models.base import MongoBaseModel


class TaskStatus(str, Enum):
    OPEN = "open"  # פתוח
    IN_PROGRESS = "in_progress"  # בתהליך
    COMPLETED = "completed"  # הושלם


class TaskPriority(str, Enum):
    LOW = "low"  # נמוכה
    NORMAL = "normal"  # רגילה
    HIGH = "high"  # גבוהה
    URGENT = "urgent"  # דחוף


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
    tags: List[str] = Field(default_factory=list)
    links: List[str] = Field(default_factory=list)
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
    column_order: Optional[int] = None


class TaskStatusUpdate(BaseModel):
    """עדכון סטטוס בלבד - לגרירה"""
    status: TaskStatus
    column_order: int = 0


class TaskOrderUpdate(BaseModel):
    """עדכון סדר בעמודה - לגרירה בתוך עמודה"""
    column_order: int


class Task(MongoBaseModel, TaskBase):
    completed_at: Optional[datetime] = None


class TaskWithContext(Task):
    """משימה עם פרטי פרויקט ולקוח - לתצוגות גלובליות"""
    project_name: Optional[str] = None
    client_name: Optional[str] = None
    client_color: Optional[str] = None
