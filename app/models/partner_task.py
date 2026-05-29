"""מודל משימת שותף (לוח mriox).

אוסף נפרד לחלוטין - partner_tasks. מבודד משאר TaskFlow ולא נוגע
בלוגיקה או באוספים הקיימים. ראו docs/taskflow-partner-spec.md.
"""
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.base import MongoBaseModel


class PartnerTaskBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)  # שם המשימה
    deadline: Optional[datetime] = None  # תאריך דדליין
    # "מה קורה אם עובר הדדליין" - טקסט חופשי ידני
    consequence: str = Field(default="", max_length=1000)
    # אחרי כמה ימים מרגע יצירת המשימה תתחיל התזכורת היומית
    reminder_after_days: int = Field(default=3, ge=0, le=3650)
    # הערת התקדמות חופשית שהשותף כותב ועורך מהמסך שלו (לא נקבע ע"י אמיר)
    progress_note: str = Field(default="", max_length=2000)


class PartnerTaskCreate(PartnerTaskBase):
    pass


class PartnerTaskUpdate(BaseModel):
    """עדכון חלקי - כל השדות אופציונליים (model_dump(exclude_unset=True))."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    deadline: Optional[datetime] = None
    consequence: Optional[str] = Field(default=None, max_length=1000)
    reminder_after_days: Optional[int] = Field(default=None, ge=0, le=3650)
    progress_note: Optional[str] = Field(default=None, max_length=2000)
    is_done: Optional[bool] = None


class PartnerTask(MongoBaseModel, PartnerTaskBase):
    is_done: bool = False
    # תאריך התזכורת האחרונה שנשלחה, כמחרוזת "YYYY-MM-DD" בשעון השותף.
    # נשמר כמחרוזת (ולא datetime) כדי שבדיקת "כבר נשלח היום" תהיה השוואת
    # תאריך פשוטה וחסינת אזורי-זמן.
    last_reminded_date: Optional[str] = None
