"""ראוטר לניהול פרויקטים - API"""
from typing import List
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Request, status, Query
from app.core.database import get_database
from app.core.auth import require_api_auth
from app.core.db_utils import validate_object_id
from app.models.project import (
    Project,
    ProjectCreate,
    ProjectUpdate,
    ProjectWithStats,
)

router = APIRouter()


def _serialize(doc: dict) -> dict:
    """ממיר מסמך MongoDB לתצוגה תקינה"""
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def _enrich_project(project: dict, db) -> dict:
    """מעשיר פרויקט בנתוני לקוח, סטטיסטיקות ותגיות."""
    project = _serialize(project)
    project_id_str = project["_id"]

    # ספירת משימות. משימות בארכיון מוסתרות מכל הספירות.
    open_tasks = await db.tasks.count_documents({
        "project_id": project_id_str,
        "status": {"$in": ["open", "in_progress"]},
        "archived": {"$ne": True},
    })
    completed_tasks = await db.tasks.count_documents({
        "project_id": project_id_str,
        "status": "completed",
        "archived": {"$ne": True},
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

    # פרטי תגיות
    project["tag_details"] = []
    if project.get("tags"):
        try:
            tag_ids = [ObjectId(tid) for tid in project["tags"] if ObjectId.is_valid(tid)]
            if tag_ids:
                tags_cursor = db.tags.find({"_id": {"$in": tag_ids}})
                tag_docs = await tags_cursor.to_list(length=100)
                project["tag_details"] = [
                    {"_id": str(t["_id"]), "name": t.get("name"), "color": t.get("color", "#3B82F6")}
                    for t in tag_docs
                ]
        except (InvalidId, TypeError):
            pass

    return project


@router.get("", response_model=List[ProjectWithStats])
async def list_projects(
    request: Request,
    include_inactive: bool = Query(False, description="האם לכלול פרויקטים שהושלמו או בארכיון"),
):
    """החזרת פרויקטים עם סטטיסטיקות ופרטי לקוח"""
    require_api_auth(request)
    db = get_database()

    # ברירת מחדל: רק פעילים + בהמתנה
    query = {}
    if not include_inactive:
        query["status"] = {"$in": ["active", "pending"]}

    cursor = db.projects.find(query).sort([("status", 1), ("name", 1)])
    projects = await cursor.to_list(length=1000)

    if not projects:
        return []

    project_ids = [str(p["_id"]) for p in projects]

    # איסוף מזהי לקוחות ותגיות ייחודיים מכל הפרויקטים
    client_obj_ids: List[ObjectId] = []
    seen_clients = set()
    for p in projects:
        cid = p.get("client_id")
        if cid and cid not in seen_clients:
            try:
                client_obj_ids.append(ObjectId(cid))
                seen_clients.add(cid)
            except (InvalidId, TypeError):
                pass

    tag_obj_ids: List[ObjectId] = []
    seen_tags = set()
    for p in projects:
        for tid in p.get("tags") or []:
            if tid in seen_tags:
                continue
            if ObjectId.is_valid(tid):
                tag_obj_ids.append(ObjectId(tid))
                seen_tags.add(tid)

    # ספירת משימות לכל הפרויקטים ב-aggregation אחד
    task_counts: dict[str, dict[str, int]] = {}
    counts_pipeline = [
        {"$match": {
            "project_id": {"$in": project_ids},
            "archived": {"$ne": True},
            "status": {"$in": ["open", "in_progress", "completed"]},
        }},
        {"$group": {
            "_id": {
                "project_id": "$project_id",
                "bucket": {
                    "$cond": [
                        {"$eq": ["$status", "completed"]},
                        "completed",
                        "open",
                    ]
                },
            },
            "count": {"$sum": 1},
        }},
    ]
    async for row in db.tasks.aggregate(counts_pipeline):
        pid = row["_id"]["project_id"]
        bucket = row["_id"]["bucket"]
        task_counts.setdefault(pid, {})[bucket] = row["count"]

    # שליפת כל הלקוחות והתגיות הרלוונטיים בשתי קריאות
    clients_by_id: dict[str, dict] = {}
    if client_obj_ids:
        async for c in db.clients.find(
            {"_id": {"$in": client_obj_ids}},
            {"name": 1, "color": 1},
        ):
            clients_by_id[str(c["_id"])] = c

    tags_by_id: dict[str, dict] = {}
    if tag_obj_ids:
        async for t in db.tags.find(
            {"_id": {"$in": tag_obj_ids}},
            {"name": 1, "color": 1},
        ):
            tags_by_id[str(t["_id"])] = t

    # הרכבת התוצאה בזיכרון
    result = []
    for project in projects:
        project = _serialize(project)
        pid = project["_id"]

        counts = task_counts.get(pid, {})
        project["open_tasks_count"] = counts.get("open", 0)
        project["completed_tasks_count"] = counts.get("completed", 0)

        project["client_name"] = None
        project["client_color"] = None
        cid = project.get("client_id")
        if cid and cid in clients_by_id:
            client = clients_by_id[cid]
            project["client_name"] = client.get("name")
            project["client_color"] = client.get("color")

        tag_details = []
        for tid in project.get("tags") or []:
            tag = tags_by_id.get(tid)
            if tag:
                tag_details.append({
                    "_id": str(tag["_id"]),
                    "name": tag.get("name"),
                    "color": tag.get("color", "#3B82F6"),
                })
        project["tag_details"] = tag_details

        result.append(project)

    return result


@router.post("", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(request: Request, project_data: ProjectCreate):
    """יצירת פרויקט חדש"""
    require_api_auth(request)
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


@router.get("/pinned")
async def list_pinned_projects(request: Request):
    """החזרת הפרויקטים הנעוצים (לסיידבר) - רשימה קלה: id, שם, וצבע הלקוח.

    מוגדר לפני /{project_id} כדי ש-"pinned" לא ייתפס כמזהה פרויקט.
    מחזיר את כל הנעוצים ללא תלות בסטטוס, ממוין לפי שם.
    """
    require_api_auth(request)
    db = get_database()

    cursor = db.projects.find(
        {"pinned": True},
        {"name": 1, "client_id": 1},
    ).sort("name", 1)
    projects = await cursor.to_list(length=1000)

    if not projects:
        return []

    # פתרון bulk של צבעי הלקוחות (בדומה ל-list_projects)
    client_obj_ids: List[ObjectId] = []
    seen = set()
    for p in projects:
        cid = p.get("client_id")
        if cid and cid not in seen:
            try:
                client_obj_ids.append(ObjectId(cid))
                seen.add(cid)
            except (InvalidId, TypeError):
                pass

    colors_by_client: dict[str, str] = {}
    if client_obj_ids:
        async for c in db.clients.find(
            {"_id": {"$in": client_obj_ids}},
            {"color": 1},
        ):
            colors_by_client[str(c["_id"])] = c.get("color")

    return [
        {
            "_id": str(p["_id"]),
            "name": p.get("name"),
            "client_color": colors_by_client.get(p.get("client_id") or ""),
        }
        for p in projects
    ]


@router.get("/{project_id}", response_model=ProjectWithStats)
async def get_project(request: Request, project_id: str):
    """החזרת פרויקט לפי ID עם פרטים מלאים"""
    require_api_auth(request)
    db = get_database()

    obj_id = validate_object_id(project_id)
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
    require_api_auth(request)
    db = get_database()

    obj_id = validate_object_id(project_id)

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
    המשימות והמסמכים של הפרויקט נמחקים גם הם.
    """
    require_api_auth(request)
    db = get_database()

    obj_id = validate_object_id(project_id)
    project_id_str = str(obj_id)

    # מחיקת המשימות והמסמכים של הפרויקט
    await db.tasks.delete_many({"project_id": project_id_str})
    await db.project_documents.delete_many({"project_id": project_id_str})

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
    require_api_auth(request)
    db = get_database()

    obj_id = validate_object_id(project_id)
    project = await db.projects.find_one({"_id": obj_id})
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="פרויקט לא נמצא"
        )

    cursor = db.tasks.find({"project_id": str(obj_id)}).sort([("status", 1), ("column_order", 1)])
    tasks = await cursor.to_list(length=1000)
    return [_serialize(t) for t in tasks]
