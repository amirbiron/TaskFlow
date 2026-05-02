"""ראוטר לניהול תגיות - API"""
from typing import List
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Request, status
from app.core.database import get_database
from app.core.auth import require_api_auth
from app.models.tag import Tag, TagCreate, TagUpdate, TagWithUsage

router = APIRouter()


def _validate_object_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="מזהה לא תקין"
        )


def _serialize(doc: dict) -> dict:
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


@router.get("", response_model=List[TagWithUsage])
async def list_tags(request: Request):
    """החזרת כל התגיות עם מידע על שימוש"""
    require_api_auth(request)
    db = get_database()

    cursor = db.tags.find().sort("name", 1)
    tags = await cursor.to_list(length=1000)

    result = []
    for tag in tags:
        tag_id_str = str(tag["_id"])

        tasks_count = await db.tasks.count_documents({"tags": tag_id_str})
        projects_count = await db.projects.count_documents({"tags": tag_id_str})

        tag = _serialize(tag)
        tag["tasks_count"] = tasks_count
        tag["projects_count"] = projects_count
        tag["usage_count"] = tasks_count + projects_count
        result.append(tag)

    return result


@router.post("", response_model=Tag, status_code=status.HTTP_201_CREATED)
async def create_tag(request: Request, tag_data: TagCreate):
    """יצירת תגית חדשה"""
    require_api_auth(request)
    db = get_database()

    # בדיקה שאין כבר תגית עם אותו שם
    existing = await db.tags.find_one({"name": tag_data.name})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="תגית עם השם הזה כבר קיימת"
        )

    now = datetime.utcnow()
    doc = tag_data.model_dump()
    doc["usage_count"] = 0
    doc["created_at"] = now
    doc["updated_at"] = now

    result = await db.tags.insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    return doc


@router.get("/{tag_id}", response_model=Tag)
async def get_tag(request: Request, tag_id: str):
    """החזרת תגית לפי ID"""
    require_api_auth(request)
    db = get_database()

    obj_id = _validate_object_id(tag_id)
    tag = await db.tags.find_one({"_id": obj_id})

    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="תגית לא נמצאה"
        )

    return _serialize(tag)


@router.put("/{tag_id}", response_model=Tag)
async def update_tag(request: Request, tag_id: str, update_data: TagUpdate):
    """עדכון תגית"""
    require_api_auth(request)
    db = get_database()

    obj_id = _validate_object_id(tag_id)

    update_doc = {k: v for k, v in update_data.model_dump(exclude_unset=True).items() if v is not None}

    # אם משנים שם - לבדוק שאין כפילות
    if "name" in update_doc:
        existing = await db.tags.find_one({
            "name": update_doc["name"],
            "_id": {"$ne": obj_id}
        })
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="תגית עם השם הזה כבר קיימת"
            )

    update_doc["updated_at"] = datetime.utcnow()

    result = await db.tags.find_one_and_update(
        {"_id": obj_id},
        {"$set": update_doc},
        return_document=True,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="תגית לא נמצאה"
        )

    return _serialize(result)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(request: Request, tag_id: str):
    """
    מחיקת תגית.
    התגית מוסרת מכל המשימות והפרויקטים שמשויכים אליה.
    """
    require_api_auth(request)
    db = get_database()

    obj_id = _validate_object_id(tag_id)
    tag_id_str = str(obj_id)

    # הסרת התגית מכל המשימות והפרויקטים
    await db.tasks.update_many(
        {"tags": tag_id_str},
        {"$pull": {"tags": tag_id_str}, "$set": {"updated_at": datetime.utcnow()}}
    )
    await db.projects.update_many(
        {"tags": tag_id_str},
        {"$pull": {"tags": tag_id_str}, "$set": {"updated_at": datetime.utcnow()}}
    )

    # מחיקת התגית עצמה
    result = await db.tags.delete_one({"_id": obj_id})

    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="תגית לא נמצאה"
        )

    return None
