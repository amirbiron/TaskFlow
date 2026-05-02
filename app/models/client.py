"""מודל לקוח"""
from typing import Optional
from pydantic import BaseModel, Field
from app.models.base import MongoBaseModel


class ClientBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: Optional[str] = None
    phone: Optional[str] = None
    telegram: Optional[str] = None
    notes: Optional[str] = None
    color: str = Field(default="#3B82F6", pattern=r"^#[0-9A-Fa-f]{6}$")


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    telegram: Optional[str] = None
    notes: Optional[str] = None
    color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")


class Client(MongoBaseModel, ClientBase):
    pass


class ClientWithStats(Client):
    """לקוח עם נתונים סטטיסטיים נלווים - לתצוגות רשימה"""
    active_projects_count: int = 0
    open_tasks_count: int = 0
