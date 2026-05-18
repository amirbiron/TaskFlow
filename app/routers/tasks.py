"""ראוטר לניהול משימות - API"""
import logging
from typing import List, Optional
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import PyMongoError
from fastapi import APIRouter, HTTPException, Request, status, Query
from app.core.database import get_database
from app.core.auth import require_api_auth
from app.core.markdown_renderer import markdown_to_html
from app.models.task import (
    Task,
    TaskCreate,
    TaskUpdate,
    TaskStatus,
    TaskStatusUpdate,
    TaskOrderUpdate,
    TaskWithContext,
)
from pydantic import BaseModel, Field

router = APIRouter()
logger = logging.getLogger(__name__)


# מקסימום סביר לתיאור משימה - מעט גדול יותר מהערה כדי לאפשר תיאורים מפורטים.
MAX_TASK_DESCRIPTION = 50_000


class TaskRenderRequest(BaseModel):
    """תצוגה מקדימה של תיאור משימה ב-Markdown."""
    text: str = Field(default="", max_length=MAX_TASK_DESCRIPTION)


def _render_description(text: Optional[str]) -> Optional[str]:
    """רינדור description ל-HTML. None/ריק → None (בלי לשמור מחרוזת ריקה)."""
    if not text or not text.strip():
        return None
    html, _ = markdown_to_html(text)
    return html


@router.post("/_render")
async def render_task_description(request: Request, body: TaskRenderRequest):
    """רינדור Markdown ל-HTML לתצוגה מקדימה (ללא שמירה)."""
    require_api_auth(request)
    html, _ = markdown_to_html(body.text)
    return {"html": html}


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


async def _enrich_task(task: dict, db, comments_count: Optional[int] = None) -> dict:
    """מעשיר משימה בפרטי פרויקט, לקוח ותגיות.

    אם `comments_count` סופק - משתמשים בו (חוסך שאילתה לכל משימה).
    אחרת מבצעים count_documents בודד (מתאים לקריאת משימה יחידה).
    """
    task = _serialize(task)

    task["project_name"] = None
    task["client_name"] = None
    task["client_color"] = None

    # פרטי פרויקט
    if task.get("project_id"):
        try:
            project = await db.projects.find_one(
                {"_id": ObjectId(task["project_id"])},
                {"name": 1, "client_id": 1}
            )
            if project:
                task["project_name"] = project.get("name")
                if not task.get("client_id") and project.get("client_id"):
                    task["client_id"] = project["client_id"]
        except (InvalidId, TypeError):
            pass

    # פרטי לקוח
    if task.get("client_id"):
        try:
            client = await db.clients.find_one(
                {"_id": ObjectId(task["client_id"])},
                {"name": 1, "color": 1}
            )
            if client:
                task["client_name"] = client.get("name")
                task["client_color"] = client.get("color")
        except (InvalidId, TypeError):
            pass

    # ספירת הערות (לתצוגת המונה בכרטיס/בעמוד)
    if comments_count is not None:
        task["comments_count"] = comments_count
    else:
        try:
            task["comments_count"] = await db.task_comments.count_documents(
                {"task_id": str(task["_id"])}
            )
        except Exception:
            task["comments_count"] = 0

    # פרטי תגיות
    task["tag_details"] = []
    if task.get("tags"):
        try:
            tag_ids = [ObjectId(tid) for tid in task["tags"] if ObjectId.is_valid(tid)]
            if tag_ids:
                tags_cursor = db.tags.find({"_id": {"$in": tag_ids}})
                tag_docs = await tags_cursor.to_list(length=100)
                task["tag_details"] = [
                    {"_id": str(t["_id"]), "name": t.get("name"), "color": t.get("color", "#3B82F6")}
                    for t in tag_docs
                ]
        except (InvalidId, TypeError):
            pass

    return task


async def _validate_project(db, project_id: str):
    """בודק שהפרויקט קיים"""
    try:
        project = await db.projects.find_one({"_id": ObjectId(project_id)})
        if not project:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="פרויקט לא נמצא"
            )
        return project
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="מזהה פרויקט לא תקין"
        )


async def _validate_client(db, client_id: str):
    """בודק שהלקוח קיים"""
    try:
        client = await db.clients.find_one({"_id": ObjectId(client_id)})
        if not client:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="לקוח לא נמצא"
            )
        return client
    except InvalidId:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="מזהה לקוח לא תקין"
        )


async def _next_column_order(db, project_id: str, status_value: str) -> int:
    """מחזיר את ה-column_order הבא בעמודה (לסוף הרשימה)"""
    last = await db.tasks.find(
        {"project_id": project_id, "status": status_value}
    ).sort("column_order", -1).limit(1).to_list(length=1)

    if last:
        return last[0].get("column_order", 0) + 1
    return 0


@router.get("", response_model=List[TaskWithContext])
async def list_tasks(
    request: Request,
    project_id: Optional[str] = Query(None, description="סינון לפי פרויקט"),
    client_id: Optional[str] = Query(None, description="סינון לפי לקוח"),
    status_filter: Optional[str] = Query(None, alias="status", description="סינון לפי סטטוס"),
    archived: Optional[bool] = Query(None, description="true: רק ארכיון, false: ללא ארכיון, None: ברירת מחדל מסתיר ארכיון"),
    include_archived: bool = Query(False, description="לכלול גם משימות בארכיון"),
):
    """החזרת רשימת משימות עם פרטי פרויקט ולקוח"""
    require_api_auth(request)
    db = get_database()

    query = {}
    if project_id:
        query["project_id"] = project_id
    if client_id:
        query["client_id"] = client_id
    if status_filter:
        query["status"] = status_filter

    # ברירת מחדל: לא להחזיר משימות בארכיון. archived=true מחזיר רק ארכיון,
    # archived=false או include_archived=true מאפשרים שליטה מפורשת.
    if archived is True:
        query["archived"] = True
    elif archived is False:
        query["archived"] = {"$ne": True}
    elif not include_archived:
        query["archived"] = {"$ne": True}

    cursor = db.tasks.find(query).sort([("status", 1), ("column_order", 1)])
    tasks = await cursor.to_list(length=2000)

    if not tasks:
        return []

    # ספירת הערות ב-batch אחד במקום שאילתה לכל משימה (מונע N+1).
    # comments_count הוא מונה תצוגה לא-קריטי: אם השאילתה נכשלת מציגים 0
    # במקום לשבור את כל רשימת המשימות.
    task_ids = [str(t["_id"]) for t in tasks]
    counts: dict[str, int] = {}
    try:
        async for row in db.task_comments.aggregate([
            {"$match": {"task_id": {"$in": task_ids}}},
            {"$group": {"_id": "$task_id", "count": {"$sum": 1}}},
        ]):
            counts[row["_id"]] = row["count"]
    except PyMongoError as exc:
        logger.warning(
            "Failed to aggregate comment counts for %d tasks: %s",
            len(task_ids), exc, exc_info=True,
        )
        counts = {}

    # שליפה bulk של projects לכל המשימות (גם בשביל fallback ל-client_id)
    project_obj_ids: List[ObjectId] = []
    seen_projects: set = set()
    for t in tasks:
        pid = t.get("project_id")
        if pid and pid not in seen_projects and ObjectId.is_valid(pid):
            project_obj_ids.append(ObjectId(pid))
            seen_projects.add(pid)

    projects_by_id: dict[str, dict] = {}
    if project_obj_ids:
        async for p in db.projects.find(
            {"_id": {"$in": project_obj_ids}},
            {"name": 1, "client_id": 1},
        ):
            projects_by_id[str(p["_id"])] = p

    # שליפה bulk של clients (כולל אלה שמגיעים דרך fallback של פרויקט)
    client_obj_ids: List[ObjectId] = []
    seen_clients: set = set()
    for t in tasks:
        cid = t.get("client_id")
        if not cid:
            project = projects_by_id.get(t.get("project_id") or "")
            cid = (project or {}).get("client_id")
        if cid and cid not in seen_clients and ObjectId.is_valid(cid):
            client_obj_ids.append(ObjectId(cid))
            seen_clients.add(cid)

    clients_by_id: dict[str, dict] = {}
    if client_obj_ids:
        async for c in db.clients.find(
            {"_id": {"$in": client_obj_ids}},
            {"name": 1, "color": 1},
        ):
            clients_by_id[str(c["_id"])] = c

    # שליפה bulk של תגיות
    tag_obj_ids: List[ObjectId] = []
    seen_tags: set = set()
    for t in tasks:
        for tid in t.get("tags") or []:
            if tid in seen_tags:
                continue
            if ObjectId.is_valid(tid):
                tag_obj_ids.append(ObjectId(tid))
                seen_tags.add(tid)

    tags_by_id: dict[str, dict] = {}
    if tag_obj_ids:
        async for tg in db.tags.find(
            {"_id": {"$in": tag_obj_ids}},
            {"name": 1, "color": 1},
        ):
            tags_by_id[str(tg["_id"])] = tg

    # הרכבת התוצאה בזיכרון
    result = []
    for task in tasks:
        task = _serialize(task)
        task["project_name"] = None
        task["client_name"] = None
        task["client_color"] = None

        project = projects_by_id.get(task.get("project_id") or "")
        if project:
            task["project_name"] = project.get("name")
            if not task.get("client_id") and project.get("client_id"):
                task["client_id"] = project["client_id"]

        cid = task.get("client_id")
        if cid:
            client = clients_by_id.get(cid)
            if client:
                task["client_name"] = client.get("name")
                task["client_color"] = client.get("color")

        task["comments_count"] = counts.get(task["_id"], 0)

        tag_details = []
        for tid in task.get("tags") or []:
            tg = tags_by_id.get(tid)
            if tg:
                tag_details.append({
                    "_id": str(tg["_id"]),
                    "name": tg.get("name"),
                    "color": tg.get("color", "#3B82F6"),
                })
        task["tag_details"] = tag_details

        result.append(task)

    return result


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
async def create_task(request: Request, task_data: TaskCreate):
    """יצירת משימה חדשה"""
    require_api_auth(request)
    db = get_database()

    # ולידציה של פרויקט
    project = await _validate_project(db, task_data.project_id)

    # ולידציה של לקוח (אם סופק)
    if task_data.client_id:
        await _validate_client(db, task_data.client_id)

    now = datetime.utcnow()
    doc = task_data.model_dump()
    doc["created_at"] = now
    doc["updated_at"] = now
    doc["completed_at"] = now if doc["status"] == TaskStatus.COMPLETED else None
    doc["description_html"] = _render_description(doc.get("description"))

    # קביעת column_order אוטומטית בסוף העמודה
    doc["column_order"] = await _next_column_order(db, doc["project_id"], doc["status"])

    result = await db.tasks.insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    return doc


@router.get("/{task_id}", response_model=TaskWithContext)
async def get_task(request: Request, task_id: str):
    """החזרת משימה לפי ID"""
    require_api_auth(request)
    db = get_database()

    obj_id = _validate_object_id(task_id)
    task = await db.tasks.find_one({"_id": obj_id})

    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="משימה לא נמצאה"
        )

    return await _enrich_task(task, db)


@router.put("/{task_id}", response_model=Task)
async def update_task(request: Request, task_id: str, update_data: TaskUpdate):
    """עדכון משימה"""
    require_api_auth(request)
    db = get_database()

    obj_id = _validate_object_id(task_id)

    # נקבל את המשימה הקיימת לבדיקה
    existing = await db.tasks.find_one({"_id": obj_id})
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="משימה לא נמצאה"
        )

    update_doc = {k: v for k, v in update_data.model_dump(exclude_unset=True).items()}

    # אם description התעדכן (כולל ל-None) - לרנדר מחדש את ה-HTML
    if "description" in update_doc:
        update_doc["description_html"] = _render_description(update_doc["description"])

    # ולידציה של פרויקט
    if "project_id" in update_doc and update_doc["project_id"]:
        await _validate_project(db, update_doc["project_id"])

    # ולידציה של לקוח
    if "client_id" in update_doc and update_doc["client_id"]:
        await _validate_client(db, update_doc["client_id"])

    # אם הסטטוס השתנה ל"הושלם" - לרשום completed_at
    new_status = update_doc.get("status")
    if new_status:
        if new_status == TaskStatus.COMPLETED and existing.get("status") != TaskStatus.COMPLETED:
            update_doc["completed_at"] = datetime.utcnow()
        elif new_status != TaskStatus.COMPLETED and existing.get("status") == TaskStatus.COMPLETED:
            update_doc["completed_at"] = None

    # אם archived השתנה - לסנכרן archived_at בהתאם
    if "archived" in update_doc:
        new_archived = bool(update_doc["archived"])
        was_archived = bool(existing.get("archived"))
        if new_archived and not was_archived:
            update_doc["archived_at"] = datetime.utcnow()
        elif not new_archived and was_archived:
            update_doc["archived_at"] = None

    update_doc["updated_at"] = datetime.utcnow()

    result = await db.tasks.find_one_and_update(
        {"_id": obj_id},
        {"$set": update_doc},
        return_document=True,
    )

    return _serialize(result)


@router.patch("/{task_id}/status", response_model=Task)
async def update_task_status(
    request: Request,
    task_id: str,
    update: TaskStatusUpdate,
):
    """עדכון סטטוס בלבד (לגרירה בין עמודות)"""
    require_api_auth(request)
    db = get_database()

    obj_id = _validate_object_id(task_id)
    existing = await db.tasks.find_one({"_id": obj_id})
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="משימה לא נמצאה"
        )

    update_doc = {
        "status": update.status,
        "column_order": update.column_order,
        "updated_at": datetime.utcnow(),
    }

    # טיפול ב-completed_at
    if update.status == TaskStatus.COMPLETED and existing.get("status") != TaskStatus.COMPLETED:
        update_doc["completed_at"] = datetime.utcnow()
    elif update.status != TaskStatus.COMPLETED and existing.get("status") == TaskStatus.COMPLETED:
        update_doc["completed_at"] = None

    result = await db.tasks.find_one_and_update(
        {"_id": obj_id},
        {"$set": update_doc},
        return_document=True,
    )

    return _serialize(result)


@router.patch("/{task_id}/order", response_model=Task)
async def update_task_order(
    request: Request,
    task_id: str,
    update: TaskOrderUpdate,
):
    """עדכון סדר בלבד (לגרירה בתוך עמודה)"""
    require_api_auth(request)
    db = get_database()

    obj_id = _validate_object_id(task_id)

    result = await db.tasks.find_one_and_update(
        {"_id": obj_id},
        {"$set": {
            "column_order": update.column_order,
            "updated_at": datetime.utcnow(),
        }},
        return_document=True,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="משימה לא נמצאה"
        )

    return _serialize(result)


@router.post("/reorder")
async def reorder_tasks(request: Request, payload: dict):
    """
    עדכון סדר/סטטוס של מספר משימות במכה אחת.
    מבנה payload:
    {
        "tasks": [
            {"id": "...", "status": "open", "column_order": 0},
            ...
        ]
    }
    """
    require_api_auth(request)
    db = get_database()

    tasks_to_update = payload.get("tasks", [])
    if not tasks_to_update:
        return {"updated": 0}

    now = datetime.utcnow()
    updated = 0

    for t in tasks_to_update:
        try:
            task_obj_id = ObjectId(t["id"])
        except (InvalidId, KeyError):
            continue

        update_doc = {
            "column_order": t.get("column_order", 0),
            "updated_at": now,
        }

        new_status = t.get("status")
        if new_status:
            update_doc["status"] = new_status

            existing = await db.tasks.find_one({"_id": task_obj_id}, {"status": 1})
            if existing:
                if new_status == TaskStatus.COMPLETED and existing.get("status") != TaskStatus.COMPLETED:
                    update_doc["completed_at"] = now
                elif new_status != TaskStatus.COMPLETED and existing.get("status") == TaskStatus.COMPLETED:
                    update_doc["completed_at"] = None

        result = await db.tasks.update_one(
            {"_id": task_obj_id},
            {"$set": update_doc}
        )
        if result.modified_count > 0:
            updated += 1

    return {"updated": updated}


class ArchiveRequest(BaseModel):
    """בקשה לארכוב/שחזור של משימות לפי מזהים."""
    task_ids: List[str] = Field(default_factory=list)


@router.post("/archive")
async def archive_tasks(request: Request, payload: ArchiveRequest):
    """העברת רשימת משימות לארכיון."""
    require_api_auth(request)
    db = get_database()

    if not payload.task_ids:
        return {"archived": 0}

    obj_ids = []
    for tid in payload.task_ids:
        try:
            obj_ids.append(ObjectId(tid))
        except InvalidId:
            continue

    if not obj_ids:
        return {"archived": 0}

    now = datetime.utcnow()
    result = await db.tasks.update_many(
        {"_id": {"$in": obj_ids}, "archived": {"$ne": True}},
        {"$set": {"archived": True, "archived_at": now, "updated_at": now}},
    )
    return {"archived": result.modified_count}


@router.post("/unarchive")
async def unarchive_tasks(request: Request, payload: ArchiveRequest):
    """החזרת רשימת משימות מהארכיון."""
    require_api_auth(request)
    db = get_database()

    if not payload.task_ids:
        return {"unarchived": 0}

    obj_ids = []
    for tid in payload.task_ids:
        try:
            obj_ids.append(ObjectId(tid))
        except InvalidId:
            continue

    if not obj_ids:
        return {"unarchived": 0}

    now = datetime.utcnow()
    result = await db.tasks.update_many(
        {"_id": {"$in": obj_ids}, "archived": True},
        {"$set": {"archived": False, "archived_at": None, "updated_at": now}},
    )
    return {"unarchived": result.modified_count}


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(request: Request, task_id: str):
    """מחיקת משימה"""
    require_api_auth(request)
    db = get_database()

    obj_id = _validate_object_id(task_id)
    result = await db.tasks.delete_one({"_id": obj_id})

    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="משימה לא נמצאה"
        )

    # מחיקת ההערות הקשורות (cascade)
    await db.task_comments.delete_many({"task_id": task_id})

    # מחיקת קבצים מצורפים (cascade) - מבודדים את ניקיון R2 ממחיקת ה-DB
    # כדי שכשל ב-R2 לא ישאיר רשומות יתומות באוסף attachments.
    from app.core import r2 as _r2  # ייבוא דחוי כדי לא לחייב את boto3 בעת ייבוא הראוטר
    try:
        cursor = db.attachments.find({"task_id": task_id}, {"file_url": 1})
        async for att in cursor:
            key = _r2.key_from_public_url(att.get("file_url") or "")
            if not key:
                continue
            try:
                await _r2.delete_object(key)
            except Exception:
                # נכשל למחוק מ-R2 - נשאיר יתום שם, אבל נמשיך לנקות את ה-DB
                logger.warning("Failed to delete R2 object on cascade", exc_info=True)
    except Exception:
        logger.exception("R2 cascade cleanup failed")

    try:
        await db.attachments.delete_many({"task_id": task_id})
    except Exception:
        logger.exception("Cascade delete of attachment records failed")

    return None
