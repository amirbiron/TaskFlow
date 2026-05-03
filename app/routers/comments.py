"""ראוטר להערות (קומנטים) על משימות - תוכן ב-Markdown."""
from datetime import datetime
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request, status
from app.core.database import get_database
from app.core.auth import require_api_auth
from app.core.db_utils import validate_object_id
from app.core.markdown_renderer import markdown_to_html
from app.models.comment import CommentCreate, CommentUpdate, MAX_COMMENT_BODY
from pydantic import BaseModel, Field

router = APIRouter()


class CommentRenderRequest(BaseModel):
    """תצוגה מקדימה של גוף הערה ב-Markdown."""
    text: str = Field(default="", max_length=MAX_COMMENT_BODY)


@router.post("/comments/_render")
async def render_comment_preview(request: Request, body: CommentRenderRequest):
    """רינדור Markdown ל-HTML לתצוגה מקדימה (ללא שמירה)."""
    require_api_auth(request)
    html, _ = markdown_to_html(body.text)
    return {"html": html}


def _serialize(doc: dict) -> dict:
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def _ensure_task_exists(db, task_id: str) -> ObjectId:
    obj_id = validate_object_id(task_id)
    task = await db.tasks.find_one({"_id": obj_id}, {"_id": 1})
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="משימה לא נמצאה",
        )
    return obj_id


@router.get("/tasks/{task_id}/comments")
async def list_comments(request: Request, task_id: str):
    """רשימת הערות של משימה, ממוין כרונולוגית עולה."""
    require_api_auth(request)
    db = get_database()
    await _ensure_task_exists(db, task_id)

    cursor = db.task_comments.find({"task_id": task_id}).sort("created_at", 1)
    docs = await cursor.to_list(length=1000)
    return [_serialize(d) for d in docs]


@router.post("/tasks/{task_id}/comments", status_code=status.HTTP_201_CREATED)
async def create_comment(request: Request, task_id: str, payload: CommentCreate):
    """יצירת הערה חדשה למשימה."""
    require_api_auth(request)
    db = get_database()
    await _ensure_task_exists(db, task_id)

    body = payload.body.strip()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="גוף ההערה לא יכול להיות ריק",
        )
    html, _ = markdown_to_html(body)

    now = datetime.utcnow()
    doc = {
        "task_id": task_id,
        "body": body,
        "body_html": html,
        "edited_at": None,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.task_comments.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc


@router.put("/comments/{comment_id}")
async def update_comment(request: Request, comment_id: str, payload: CommentUpdate):
    """עריכת הערה קיימת."""
    require_api_auth(request)
    db = get_database()
    obj_id = validate_object_id(comment_id)

    body = payload.body.strip()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="גוף ההערה לא יכול להיות ריק",
        )
    html, _ = markdown_to_html(body)
    now = datetime.utcnow()

    result = await db.task_comments.find_one_and_update(
        {"_id": obj_id},
        {"$set": {
            "body": body,
            "body_html": html,
            "edited_at": now,
            "updated_at": now,
        }},
        return_document=True,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="הערה לא נמצאה",
        )

    return _serialize(result)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(request: Request, comment_id: str):
    """מחיקת הערה."""
    require_api_auth(request)
    db = get_database()
    obj_id = validate_object_id(comment_id)

    result = await db.task_comments.delete_one({"_id": obj_id})
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="הערה לא נמצאה",
        )
    return None
