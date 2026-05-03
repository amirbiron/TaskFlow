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


async def close_mongo_connection():
    """סגירת החיבור בעת כיבוי האפליקציה"""
    if db.client:
        db.client.close()
        print("👋 MongoDB connection closed")


def get_database() -> AsyncIOMotorDatabase:
    """מחזיר את אובייקט מסד הנתונים"""
    return db.db
