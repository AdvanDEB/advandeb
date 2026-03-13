"""
Main FastAPI application entry point.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import connect_to_mongo, close_mongo_connection
from app.api.routes import auth, users, documents, facts, knowledge_graph, chat, scenarios, models, ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    await connect_to_mongo()
    yield
    # Shutdown
    await close_mongo_connection()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

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
app.include_router(knowledge_graph.router, prefix="/api/graph", tags=["knowledge-graph"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(scenarios.router, prefix="/api/scenarios", tags=["scenarios"])
app.include_router(models.router, prefix="/api/models", tags=["models"])
app.include_router(ws.router, prefix="/ws", tags=["websocket"])


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
        db = await get_database()
        await db.command("ping")
        health_status["database"] = "connected"
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["database"] = f"error: {str(e)}"
    
    return health_status
