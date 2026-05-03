"""
הגדרות האפליקציה - נטענות ממשתני סביבה
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # MongoDB
    mongodb_url: str
    database_name: str = "taskflow"

    # Authentication
    app_password: str
    session_secret: str  # מפתח להצפנת ה-session cookie
    session_max_age_days: int = 30

    # Application
    app_name: str = "TaskFlow"
    debug: bool = False
    user_display_name: str = ""  # USER_DISPLAY_NAME - שם להצגה בברוך הבא בדשבורד

    # Telegram (לשלבים הבאים)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Cloudflare R2 (לשלבים הבאים)
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""
    r2_public_url: str = ""

    # גיבויים אוטומטיים של MongoDB - מימוש Python נטו (zip + Extended JSON)
    backup_enabled: bool = True
    backup_dir: str = "/var/data/backups"  # ה-disk המתמיד של Render
    backup_retention_days: int = 7  # כמה ימים לשמור גיבויים אחורה
    backup_hour: int = 3  # שעת ריצה יומית (0-23)
    backup_minute: int = 0  # דקה (0-59)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
