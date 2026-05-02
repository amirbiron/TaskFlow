"""
TaskFlow - נקודת הכניסה הראשית
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.database import connect_to_mongo, close_mongo_connection
from app.routers import auth, pages, clients, projects, tasks, tags, dashboard, documents


@asynccontextmanager
async def lifespan(app: FastAPI):
    """ניהול מחזור החיים של האפליקציה"""
    await connect_to_mongo()
    yield
    await close_mongo_connection()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="מערכת לניהול פרויקטים, משימות ולקוחות",
    version="0.5.0",
    lifespan=lifespan,
)

# קבצים סטטיים
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# ראוטרים
app.include_router(auth.router, tags=["auth"])
app.include_router(pages.router, tags=["pages"])
app.include_router(clients.router, prefix="/api/clients", tags=["clients"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(documents.router, prefix="/api/projects/{project_id}/documents", tags=["documents"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(tags.router, prefix="/api/tags", tags=["tags"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
