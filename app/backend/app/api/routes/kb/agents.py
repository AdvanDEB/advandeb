from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user
from app.core.database import get_kb_database as get_database
from app.core.dependencies import require_curator
from advandeb_kb.services.agent_service import AgentService

router = APIRouter()


@router.get("/models")
async def list_ollama_models(
    current_user: dict = Depends(require_curator),
) -> dict:
    """List available Ollama models."""
    db = get_database()
    try:
        models = await AgentService(db).list_ollama_models()
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
