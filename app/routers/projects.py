"""ראוטר לניהול פרויקטים - API"""
from typing import List, Optional
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Request, status, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from app.core.database import get_database
from app.core.auth import require_api_auth
from app.core.markdown_renderer import markdown_to_html
from app.models.project import (
    Project,
    ProjectCreate,
    ProjectUpdate,
    ProjectStatus,
    ProjectWithStats,
)

router = APIRouter()


class MarkdownRenderRequest(BaseModel):
    """גוף בקשה לרינדור Markdown לתצוגה מקדימה."""
    text: str = Field(default="", max_length=1_000_000)


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


async def _enrich_project(project: dict, db, render_notes: bool = False) -> dict:
    """מעשיר פרויקט בנתוני לקוח, סטטיסטיקות ותגיות.

    render_notes=True גם מרנדר את notes_md ל-HTML (לתצוגת פרויקט בודד).
    """
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

    # רינדור מסמך Markdown של הפרויקט (רק לתצוגת פרויקט בודד)
    if render_notes and project.get("notes_md"):
        html, _ = markdown_to_html(project["notes_md"])
        project["notes_html"] = html
    else:
        project["notes_html"] = None

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

    # ברשימה לא מחזירים את גוף ה-Markdown כדי לחסוך פס רוחב
    cursor = db.projects.find(query, {"notes_md": 0}).sort([("status", 1), ("name", 1)])
    projects = await cursor.to_list(length=1000)

    result = []
    for project in projects:
        enriched = await _enrich_project(project, db)
        result.append(enriched)

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


@router.post("/_render")
async def render_markdown_preview(request: Request, body: MarkdownRenderRequest):
    """רינדור Markdown ל-HTML לתצוגה מקדימה חיה בעורך."""
    require_api_auth(request)
    html, _ = markdown_to_html(body.text)
    return {"html": html}


@router.get("/{project_id}", response_model=ProjectWithStats)
async def get_project(request: Request, project_id: str):
    """החזרת פרויקט לפי ID עם פרטים מלאים"""
    require_api_auth(request)
    db = get_database()

    obj_id = _validate_object_id(project_id)
    project = await db.projects.find_one({"_id": obj_id})

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="פרויקט לא נמצא"
        )

    return await _enrich_project(project, db, render_notes=True)


@router.put("/{project_id}", response_model=Project)
async def update_project(
    request: Request,
    project_id: str,
    update_data: ProjectUpdate
):
    """עדכון פרויקט"""
    require_api_auth(request)
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
    require_api_auth(request)
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
    require_api_auth(request)
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


@router.get("/{project_id}/notes/download")
async def download_project_notes(request: Request, project_id: str):
    """הורדת מסמך ה-Markdown של הפרויקט כקובץ .md"""
    require_api_auth(request)
    db = get_database()

    obj_id = _validate_object_id(project_id)
    project = await db.projects.find_one(
        {"_id": obj_id},
        {"name": 1, "notes_md": 1}
    )
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="פרויקט לא נמצא"
        )

    content = project.get("notes_md") or ""
    # שם קובץ בטוח: רק תווים נפוצים, השאר מוחלפים בקו תחתון
    safe_name = "".join(
        c if c.isalnum() or c in ("-", "_", " ") else "_"
        for c in (project.get("name") or "project")
    ).strip() or "project"

    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.md"'
        },
    )
