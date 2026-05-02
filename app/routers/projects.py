"""ראוטר לניהול פרויקטים - API"""
from typing import List, Optional
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Request, status, Query
from app.core.database import get_database
from app.core.auth import is_authenticated
from app.models.project import (
    Project,
    ProjectCreate,
    ProjectUpdate,
    ProjectStatus,
    ProjectWithStats,
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


async def _enrich_project(project: dict, db) -> dict:
    """מעשיר פרויקט בנתוני לקוח וסטטיסטיקות"""
    project = _serialize(project)
    project_id_str = project["_id"]

    # ספירת משימות
    open_tasks = await db.tasks.count_documents({
        "project_id": project_id_str,
        "status": {"$in": ["open", "in_progress"]}
    })
    completed_tasks = await db.tasks.count_documents({
        "project_id": project_id_str,
        "status": "completed"
    })

    project["open_tasks_count"] = open_tasks
    project["completed_tasks_count"] = completed_tasks

    # פרטי לקוח
    project["client_name"] = None
    project["client_color"] = None
    if project.get("client_id"):
        try:
            client = await db.clients.find_one(
                {"_id": ObjectId(project["client_id"])},
                {"name": 1, "color": 1}
            )
            if client:
                project["client_name"] = client.get("name")
                project["client_color"] = client.get("color")
        except (InvalidId, TypeError):
            pass

    return project


@router.get("", response_model=List[ProjectWithStats])
async def list_projects(
    request: Request,
    include_inactive: bool = Query(False, description="האם לכלול פרויקטים שהושלמו או בארכיון"),
):
    """החזרת פרויקטים עם סטטיסטיקות ופרטי לקוח"""
    _check_auth(request)
    db = get_database()

    # ברירת מחדל: רק פעילים + בהמתנה
    query = {}
    if not include_inactive:
        query["status"] = {"$in": ["active", "pending"]}

    cursor = db.projects.find(query).sort([("status", 1), ("name", 1)])
    projects = await cursor.to_list(length=1000)

    result = []
    for project in projects:
        enriched = await _enrich_project(project, db)
        result.append(enriched)

    return result


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(request: Request, project_data: ProjectCreate):
    """יצירת פרויקט חדש"""
    _check_auth(request)
    db = get_database()

    # אם יש client_id - לוודא שהוא תקין
    if project_data.client_id:
        try:
            client = await db.clients.find_one({"_id": ObjectId(project_data.client_id)})
            if not client:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="לקוח לא נמצא"
                )
        except InvalidId:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="מזהה לקוח לא תקין"
            )

    now = datetime.utcnow()
    doc = project_data.model_dump()
    doc["created_at"] = now
    doc["updated_at"] = now

    result = await db.projects.insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    return doc


@router.get("/{project_id}", response_model=ProjectWithStats)
async def get_project(request: Request, project_id: str):
    """החזרת פרויקט לפי ID עם פרטים מלאים"""
    _check_auth(request)
    db = get_database()

    obj_id = _validate_object_id(project_id)
    project = await db.projects.find_one({"_id": obj_id})

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="פרויקט לא נמצא"
        )

    return await _enrich_project(project, db)


@router.put("/{project_id}", response_model=Project)
async def update_project(
    request: Request,
    project_id: str,
    update_data: ProjectUpdate
):
    """עדכון פרויקט"""
    _check_auth(request)
    db = get_database()

    obj_id = _validate_object_id(project_id)

    # אם מעדכנים client_id - לוודא תקינות
    update_doc = {k: v for k, v in update_data.model_dump(exclude_unset=True).items()}

    if "client_id" in update_doc and update_doc["client_id"]:
        try:
            client = await db.clients.find_one({"_id": ObjectId(update_doc["client_id"])})
            if not client:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="לקוח לא נמצא"
                )
        except InvalidId:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="מזהה לקוח לא תקין"
            )

    update_doc["updated_at"] = datetime.utcnow()

    result = await db.projects.find_one_and_update(
        {"_id": obj_id},
        {"$set": update_doc},
        return_document=True,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="פרויקט לא נמצא"
        )

    return _serialize(result)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(request: Request, project_id: str):
    """
    מחיקת פרויקט.
    המשימות של הפרויקט נמחקות גם הן.
    """
    _check_auth(request)
    db = get_database()

    obj_id = _validate_object_id(project_id)
    project_id_str = str(obj_id)

    # מחיקת המשימות של הפרויקט
    await db.tasks.delete_many({"project_id": project_id_str})

    # מחיקת הפרויקט
    result = await db.projects.delete_one({"_id": obj_id})

    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="פרויקט לא נמצא"
        )

    return None


@router.get("/{project_id}/tasks")
async def list_project_tasks(request: Request, project_id: str):
    """החזרת המשימות של פרויקט (פלייסהולדר עד שלב 4)"""
    _check_auth(request)
    db = get_database()

    obj_id = _validate_object_id(project_id)
    project = await db.projects.find_one({"_id": obj_id})
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="פרויקט לא נמצא"
        )

    cursor = db.tasks.find({"project_id": str(obj_id)}).sort([("status", 1), ("column_order", 1)])
    tasks = await cursor.to_list(length=1000)
    return [_serialize(t) for t in tasks]
