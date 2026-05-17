"""ראוטר לניהול לקוחות - API"""
from typing import List
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, status
from app.core.database import get_database
from app.core.auth import require_api_auth
from app.core.db_utils import validate_object_id
from app.core.markdown_renderer import markdown_to_html
from app.models.client import (
    Client,
    ClientCreate,
    ClientUpdate,
    ClientWithStats,
)

router = APIRouter()


def _serialize(doc: dict) -> dict:
    """ממיר מסמך MongoDB לתצוגה תקינה"""
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


def _attach_notes_html(doc: dict) -> dict:
    """מוסיף notes_html (HTML מסונן מ-Markdown) למסמך לקוח לתצוגה.

    clickable_tasks=False - אין endpoint לשמירת מצב checkboxes בהערות לקוח,
    אז מוצגים כ-disabled כדי לא להטעות.
    """
    notes = (doc or {}).get("notes") or ""
    if notes:
        html, _ = markdown_to_html(notes, clickable_tasks=False)
        doc["notes_html"] = html
    else:
        doc["notes_html"] = ""
    return doc


@router.get("")
async def list_clients(request: Request):
    """החזרת כל הלקוחות עם סטטיסטיקות"""
    require_api_auth(request)
    db = get_database()

    clients_cursor = db.clients.find().sort("name", 1)
    clients = await clients_cursor.to_list(length=1000)

    if not clients:
        return []

    client_ids = [str(c["_id"]) for c in clients]

    # ספירת פרויקטים פעילים לכל לקוח - aggregation אחד
    projects_counts: dict[str, int] = {}
    async for row in db.projects.aggregate([
        {"$match": {
            "client_id": {"$in": client_ids},
            "status": {"$in": ["active", "pending"]},
        }},
        {"$group": {"_id": "$client_id", "count": {"$sum": 1}}},
    ]):
        projects_counts[row["_id"]] = row["count"]

    # ספירת משימות פתוחות לכל לקוח - aggregation אחד
    tasks_counts: dict[str, int] = {}
    async for row in db.tasks.aggregate([
        {"$match": {
            "client_id": {"$in": client_ids},
            "status": {"$in": ["open", "in_progress"]},
            "archived": {"$ne": True},
        }},
        {"$group": {"_id": "$client_id", "count": {"$sum": 1}}},
    ]):
        tasks_counts[row["_id"]] = row["count"]

    result = []
    for client in clients:
        client = _serialize(client)
        cid = client["_id"]
        client["active_projects_count"] = projects_counts.get(cid, 0)
        client["open_tasks_count"] = tasks_counts.get(cid, 0)
        _attach_notes_html(client)
        result.append(client)

    return result


@router.get("/select-options")
async def list_clients_for_select(request: Request):
    """רשימה מצומצמת של לקוחות (id, name, color) לשימוש בטפסים"""
    require_api_auth(request)
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
    require_api_auth(request)
    db = get_database()

    now = datetime.utcnow()
    doc = client_data.model_dump()
    doc["created_at"] = now
    doc["updated_at"] = now

    result = await db.clients.insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    return doc


@router.get("/{client_id}")
async def get_client(request: Request, client_id: str):
    """החזרת לקוח לפי ID"""
    require_api_auth(request)
    db = get_database()

    obj_id = validate_object_id(client_id)
    client = await db.clients.find_one({"_id": obj_id})

    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="לקוח לא נמצא"
        )

    return _attach_notes_html(_serialize(client))


@router.put("/{client_id}")
async def update_client(
    request: Request,
    client_id: str,
    update_data: ClientUpdate
):
    """עדכון לקוח"""
    require_api_auth(request)
    db = get_database()

    obj_id = validate_object_id(client_id)

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

    return _attach_notes_html(_serialize(result))


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(request: Request, client_id: str):
    """
    מחיקת לקוח.
    הפרויקטים והמשימות שלו לא נמחקים - רק מנותקים (client_id הופך ל-null)
    """
    require_api_auth(request)
    db = get_database()

    obj_id = validate_object_id(client_id)
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
