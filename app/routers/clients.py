"""ראוטר לניהול לקוחות - API"""
from typing import List
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Request, status
from app.core.database import get_database
from app.core.auth import is_authenticated
from app.models.client import (
    Client,
    ClientCreate,
    ClientUpdate,
    ClientWithStats,
)

router = APIRouter()


def _check_auth(request: Request):
    """בדיקת הזדהות פנימית"""
    if not is_authenticated(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="לא מחובר"
        )


def _validate_object_id(id_str: str) -> ObjectId:
    """ממיר string ל-ObjectId עם טיפול בשגיאות"""
    try:
        return ObjectId(id_str)
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="מזהה לא תקין"
        )


def _serialize(doc: dict) -> dict:
    """ממיר מסמך MongoDB לתצוגה תקינה"""
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


@router.get("", response_model=List[ClientWithStats])
async def list_clients(request: Request):
    """החזרת כל הלקוחות עם סטטיסטיקות"""
    _check_auth(request)
    db = get_database()

    clients_cursor = db.clients.find().sort("name", 1)
    clients = await clients_cursor.to_list(length=1000)

    result = []
    for client in clients:
        client_id_str = str(client["_id"])

        active_projects = await db.projects.count_documents({
            "client_id": client_id_str,
            "status": {"$in": ["active", "pending"]}
        })

        open_tasks = await db.tasks.count_documents({
            "client_id": client_id_str,
            "status": {"$in": ["open", "in_progress"]}
        })

        client = _serialize(client)
        client["active_projects_count"] = active_projects
        client["open_tasks_count"] = open_tasks
        result.append(client)

    return result


@router.get("/select-options")
async def list_clients_for_select(request: Request):
    """רשימה מצומצמת של לקוחות (id, name, color) לשימוש בטפסים"""
    _check_auth(request)
    db = get_database()

    cursor = db.clients.find(
        {},
        {"_id": 1, "name": 1, "color": 1}
    ).sort("name", 1)

    clients = await cursor.to_list(length=1000)
    return [
        {
            "_id": str(c["_id"]),
            "name": c.get("name", ""),
            "color": c.get("color", "#3B82F6"),
        }
        for c in clients
    ]


@router.post("", response_model=Client, status_code=status.HTTP_201_CREATED)
async def create_client(request: Request, client_data: ClientCreate):
    """יצירת לקוח חדש"""
    _check_auth(request)
    db = get_database()

    now = datetime.utcnow()
    doc = client_data.model_dump()
    doc["created_at"] = now
    doc["updated_at"] = now

    result = await db.clients.insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    return doc


@router.get("/{client_id}", response_model=Client)
async def get_client(request: Request, client_id: str):
    """החזרת לקוח לפי ID"""
    _check_auth(request)
    db = get_database()

    obj_id = _validate_object_id(client_id)
    client = await db.clients.find_one({"_id": obj_id})

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="לקוח לא נמצא"
        )

    return _serialize(client)


@router.put("/{client_id}", response_model=Client)
async def update_client(
    request: Request,
    client_id: str,
    update_data: ClientUpdate
):
    """עדכון לקוח"""
    _check_auth(request)
    db = get_database()

    obj_id = _validate_object_id(client_id)

    update_doc = {k: v for k, v in update_data.model_dump().items() if v is not None}
    update_doc["updated_at"] = datetime.utcnow()

    result = await db.clients.find_one_and_update(
        {"_id": obj_id},
        {"$set": update_doc},
        return_document=True,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="לקוח לא נמצא"
        )

    return _serialize(result)


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(request: Request, client_id: str):
    """
    מחיקת לקוח.
    הפרויקטים והמשימות שלו לא נמחקים - רק מנותקים (client_id הופך ל-null)
    """
    _check_auth(request)
    db = get_database()

    obj_id = _validate_object_id(client_id)
    client_id_str = str(obj_id)

    await db.projects.update_many(
        {"client_id": client_id_str},
        {"$set": {"client_id": None, "updated_at": datetime.utcnow()}}
    )

    await db.tasks.update_many(
        {"client_id": client_id_str},
        {"$set": {"client_id": None, "updated_at": datetime.utcnow()}}
    )

    result = await db.clients.delete_one({"_id": obj_id})

    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="לקוח לא נמצא"
        )

    return None
