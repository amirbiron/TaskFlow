"""מודל קובץ מצורף"""
from pydantic import BaseModel, Field
from app.models.base import MongoBaseModel, PyObjectId


class AttachmentBase(BaseModel):
    task_id: PyObjectId
    filename: str
    file_url: str
    file_size: int
    mime_type: str


class AttachmentCreate(AttachmentBase):
    pass


class Attachment(MongoBaseModel, AttachmentBase):
    pass
