"""
Main FastAPI application entry point.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pathlib import Path
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.config import settings
from app.core.database import connect_to_mongo, close_mongo_connection, get_database
from app.api.routes import auth, users, documents, facts, chat, scenarios, models, ws
from app.api.routes.kb import agents as kb_agents
from app.api.routes.kb import visualization as kb_viz
from app.api.routes.kb import ingestion as kb_ingestion
from app.api.routes.kb import database as kb_db
from app.api.routes.kb import filesystem as kb_fs
from app.api.routes.kb import kg_builder as kb_kg
from advandeb_kb.services.graph_rebuild_queue import graph_rebuild_queue

FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    await connect_to_mongo()
    db = get_database()
    await graph_rebuild_queue.start(db)
    yield
    await graph_rebuild_queue.stop()
    await close_mongo_connection()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

# Trust X-Forwarded-Proto/For from the nginx reverse proxy so that
# Starlette generates https:// redirect URLs when behind HTTPS termination.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["authentication"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(facts.router, prefix="/api/facts", tags=["facts"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(scenarios.router, prefix="/api/scenarios", tags=["scenarios"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(ws.router, prefix="/ws", tags=["websocket"])
app.include_router(kb_agents.router,    prefix="/api/kb/agents",    tags=["kb"])
app.include_router(kb_viz.router,       prefix="/api/kb/viz",       tags=["kb"])
app.include_router(kb_ingestion.router, prefix="/api/kb/ingestion", tags=["kb"])
app.include_router(kb_db.router,        prefix="/api/kb/db",        tags=["kb"])
app.include_router(kb_fs.router,        prefix="/api/kb/fs",        tags=["kb"])
app.include_router(kb_kg.router,        prefix="/api/kb/kg",        tags=["kb"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
async def health():
    """Health check endpoint with database connectivity check."""
    from app.core.database import get_database
    
    health_status = {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION
    }
    
    try:
        # Check database connectivity
        db = get_database()
        await db.command("ping")
        health_status["database"] = "connected"
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["database"] = f"error: {str(e)}"
    
    return health_status


# Serve Vue SPA static assets and fall back to index.html for client-side routing.
# Must be mounted last so API routes take priority.
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        return FileResponse(FRONTEND_DIST / "index.html")
