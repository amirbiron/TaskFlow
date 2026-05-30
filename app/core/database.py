"""
חיבור למסד הנתונים MongoDB באמצעות Motor (אסינכרוני)
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import get_settings


class Database:
    client: AsyncIOMotorClient = None
    db: AsyncIOMotorDatabase = None


db = Database()


async def connect_to_mongo():
    """התחברות למסד הנתונים בעת הפעלת האפליקציה"""
    settings = get_settings()
    db.client = AsyncIOMotorClient(settings.mongodb_url)
    db.db = db.client[settings.database_name]
    await _ensure_indexes(db.db)
    print(f"✅ Connected to MongoDB: {settings.database_name}")


async def _ensure_indexes(database: AsyncIOMotorDatabase) -> None:
    """אינדקסים חיוניים לביצועים. create_index ב-Mongo idempotent."""
    await database.task_comments.create_index("task_id")
    await database.task_comments.create_index([("task_id", 1), ("created_at", 1)])
    # אינדקס לספירת משימות לכל פרויקט (עמוד הפרויקטים)
    await database.tasks.create_index([("project_id", 1), ("status", 1), ("archived", 1)])
    # אינדקס לסינון רשימת הפרויקטים לפי סטטוס
    await database.projects.create_index([("status", 1), ("name", 1)])
    # אינדקסים לעמוד הלקוחות (ספירת פרויקטים ומשימות פתוחות לכל לקוח)
    await database.clients.create_index([("name", 1)])
    await database.projects.create_index([("client_id", 1), ("status", 1)])
    await database.tasks.create_index([("client_id", 1), ("status", 1), ("archived", 1)])
    # סקירת משימות (serendipity) - שליפת המשימות הזמינות לסקירה
    await database.tasks.create_index([("status", 1), ("archived", 1), ("last_reviewed_at", 1)])
    # אינדקסים לעמוד התגיות (multikey על מערך tags)
    await database.tasks.create_index("tags")
    await database.projects.create_index("tags")
    # אינדקס לקבצים מצורפים - שליפת כל הקבצים של משימה
    await database.attachments.create_index("task_id")
    # לוח השותף - שליפת משימות פתוחות ממוינות לפי דדליין
    await database.partner_tasks.create_index([("is_done", 1), ("deadline", 1)])
    # פתקים/טיוטות של השותף - ממוינים לפי עדכון אחרון
    await database.partner_notes.create_index([("updated_at", -1)])


async def close_mongo_connection():
    """סגירת החיבור בעת כיבוי האפליקציה"""
    if db.client:
        db.client.close()
        print("👋 MongoDB connection closed")


def get_database() -> AsyncIOMotorDatabase:
    """מחזיר את אובייקט מסד הנתונים"""
    return db.db
