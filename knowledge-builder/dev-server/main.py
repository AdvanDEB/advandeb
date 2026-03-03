from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os
from dotenv import load_dotenv

from routers import knowledge, agents, data_processing, visualization, ingestion, database, filesystem
from advandeb_kb.database.mongodb import mongodb

# Load environment variables
load_dotenv()

app = FastAPI(
    title="AdvandEB Knowledge Builder",
    description="AdvanDEB knowledge-base builder for agglomeration of knowledge on physiology, morphology, anatomy, bioenergetics of organisms",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8080", "http://192.168.0.51:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["knowledge"])
app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
app.include_router(data_processing.router, prefix="/api/data", tags=["data_processing"])
app.include_router(visualization.router, prefix="/api/viz", tags=["visualization"])
app.include_router(ingestion.router, prefix="/api/ingestion", tags=["ingestion"])
app.include_router(database.router, prefix="/api/db", tags=["database"])
app.include_router(filesystem.router, prefix="/api/fs", tags=["filesystem"])

@app.on_event("startup")
async def startup():
    await mongodb.connect()


@app.on_event("shutdown")
async def shutdown():
    await mongodb.disconnect()


@app.get("/")
async def root():
    return {"message": "AdvandEB Knowledge Builder API", "version": "1.0.0"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)