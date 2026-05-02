"""ראוטר לניהול מסמכי-Markdown של פרויקט."""
from datetime import datetime
from urllib.parse import quote
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from app.core.database import get_database
from app.core.auth import require_api_auth
from app.core.db_utils import validate_object_id
from app.core.markdown_renderer import markdown_to_html
from app.models.project_document import (
    ProjectDocumentCreate,
    ProjectDocumentUpdate,
    MAX_DOCUMENT_CONTENT,
)

router = APIRouter()


class MarkdownRenderRequest(BaseModel):
    """תצוגה מקדימה של Markdown."""
    text: str = Field(default="", max_length=MAX_DOCUMENT_CONTENT)


async def _ensure_project_exists(db, project_id: str) -> ObjectId:
    obj_id = validate_object_id(project_id)
    project = await db.projects.find_one({"_id": obj_id}, {"_id": 1})
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="פרויקט לא נמצא"
        )
    return obj_id


def _summary(doc: dict) -> dict:
    """המרה לתצוגת רשימה - בלי התוכן עצמו."""
    return {
        "_id": str(doc["_id"]),
        "project_id": doc.get("project_id"),
        "title": doc.get("title", ""),
        "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
        "updated_at": doc.get("updated_at").isoformat() if doc.get("updated_at") else None,
    }


@router.post("/_render")
async def render_markdown_preview(request: Request, body: MarkdownRenderRequest, project_id: str):
    """תצוגה מקדימה של Markdown ל-HTML."""
    require_api_auth(request)
    # רק ולידציה שהפרויקט קיים, לא קוראים ממנו כלום
    db = get_database()
    await _ensure_project_exists(db, project_id)
    html, _ = markdown_to_html(body.text)
    return {"html": html}


@router.get("")
async def list_documents(request: Request, project_id: str):
    """רשימת מסמכים של פרויקט (כותרות בלבד)."""
    require_api_auth(request)
    db = get_database()
    await _ensure_project_exists(db, project_id)

    cursor = db.project_documents.find(
        {"project_id": project_id},
        {"content_md": 0},  # לא מחזירים תוכן ברשימה
    ).sort("updated_at", -1)
    docs = await cursor.to_list(length=1000)
    return [_summary(d) for d in docs]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_document(request: Request, project_id: str, doc_data: ProjectDocumentCreate):
    """יצירת מסמך חדש לפרויקט."""
    require_api_auth(request)
    db = get_database()
    await _ensure_project_exists(db, project_id)

    now = datetime.utcnow()
    doc = {
        "project_id": project_id,
        "title": doc_data.title,  # ה-validator כבר ניקה רווחים ואימת לא-ריק
        "content_md": doc_data.content_md or "",
        "created_at": now,
        "updated_at": now,
    }
    result = await db.project_documents.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    # מסמך חדש - בלי HTML מרונדר עדיין
    doc["content_html"] = None
    doc["created_at"] = now.isoformat()
    doc["updated_at"] = now.isoformat()
    return doc


@router.get("/{doc_id}")
async def get_document(request: Request, project_id: str, doc_id: str):
    """החזרת מסמך מלא + HTML מרונדר."""
    require_api_auth(request)
    db = get_database()
    await _ensure_project_exists(db, project_id)

    obj_id = validate_object_id(doc_id)
    doc = await db.project_documents.find_one({"_id": obj_id, "project_id": project_id})
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="מסמך לא נמצא"
        )

    html, _ = markdown_to_html(doc.get("content_md", ""))
    return {
        "_id": str(doc["_id"]),
        "project_id": doc.get("project_id"),
        "title": doc.get("title", ""),
        "content_md": doc.get("content_md", ""),
        "content_html": html,
        "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
        "updated_at": doc.get("updated_at").isoformat() if doc.get("updated_at") else None,
    }


@router.put("/{doc_id}")
async def update_document(
    request: Request,
    project_id: str,
    doc_id: str,
    update_data: ProjectDocumentUpdate,
):
    """עדכון מסמך."""
    require_api_auth(request)
    db = get_database()
    await _ensure_project_exists(db, project_id)

    obj_id = validate_object_id(doc_id)

    # שדות שנשלחו במפורש (לא משנה אם null) - כך null מובדל מהשמטה
    submitted = update_data.model_dump(exclude_unset=True)
    # null על title הוא בקשה לא חוקית (אין משמעות "להסיר כותרת")
    if "title" in submitted and submitted["title"] is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="title לא יכול להיות null"
        )
    # null על content_md = איפוס לתוכן ריק (במקום להעלים את הבקשה)
    if "content_md" in submitted and submitted["content_md"] is None:
        submitted["content_md"] = ""
    # title כבר עבר trim+אימות ב-validator של Pydantic
    update_doc = {k: v for k, v in submitted.items() if v is not None}

    if not update_doc:
        # אין שום שדה לעדכון - מחזירים את המסמך הקיים כפי שהוא (no-op)
        existing = await db.project_documents.find_one(
            {"_id": obj_id, "project_id": project_id}
        )
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="מסמך לא נמצא"
            )
        html, _ = markdown_to_html(existing.get("content_md", ""))
        return {
            "_id": str(existing["_id"]),
            "project_id": existing.get("project_id"),
            "title": existing.get("title", ""),
            "content_md": existing.get("content_md", ""),
            "content_html": html,
            "created_at": existing.get("created_at").isoformat() if existing.get("created_at") else None,
            "updated_at": existing.get("updated_at").isoformat() if existing.get("updated_at") else None,
        }

    update_doc["updated_at"] = datetime.utcnow()

    result = await db.project_documents.find_one_and_update(
        {"_id": obj_id, "project_id": project_id},
        {"$set": update_doc},
        return_document=True,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="מסמך לא נמצא"
        )

    html, _ = markdown_to_html(result.get("content_md", ""))
    return {
        "_id": str(result["_id"]),
        "project_id": result.get("project_id"),
        "title": result.get("title", ""),
        "content_md": result.get("content_md", ""),
        "content_html": html,
        "created_at": result.get("created_at").isoformat() if result.get("created_at") else None,
        "updated_at": result.get("updated_at").isoformat() if result.get("updated_at") else None,
    }


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(request: Request, project_id: str, doc_id: str):
    """מחיקת מסמך."""
    require_api_auth(request)
    db = get_database()
    await _ensure_project_exists(db, project_id)

    obj_id = validate_object_id(doc_id)
    result = await db.project_documents.delete_one({"_id": obj_id, "project_id": project_id})
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="מסמך לא נמצא"
        )
    return None


@router.get("/{doc_id}/download")
async def download_document(request: Request, project_id: str, doc_id: str):
    """הורדת מסמך כקובץ .md."""
    require_api_auth(request)
    db = get_database()
    await _ensure_project_exists(db, project_id)

    obj_id = validate_object_id(doc_id)
    doc = await db.project_documents.find_one(
        {"_id": obj_id, "project_id": project_id},
        {"title": 1, "content_md": 1},
    )
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="מסמך לא נמצא"
        )

    content = doc.get("content_md") or ""
    title = (doc.get("title") or "document").strip() or "document"

    # RFC 6266 / RFC 5987: filename ב-ASCII בלבד כ-fallback, ו-filename*
    # ב-UTF-8 percent-encoded לתמיכה בעברית ושפות אחרות.
    ascii_fallback = "".join(
        c if (c.isascii() and (c.isalnum() or c in ("-", "_", " "))) else "_"
        for c in title
    ).strip("_ ") or "document"
    utf8_encoded = quote(f"{title}.md", safe="")

    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_fallback}.md"; '
                f"filename*=UTF-8''{utf8_encoded}"
            )
        },
    )
