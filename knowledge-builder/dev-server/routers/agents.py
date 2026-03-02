from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from typing import Dict, Any, List, Optional
from advandeb_kb.services.agent_service import AgentService
from advandeb_kb.database.mongodb import get_database
from advandeb_kb.models.agent_models import AgentType, AgentRunRequest, AgentRunResponse
import json

router = APIRouter()

async def get_agent_service():
    db = await get_database()
    return AgentService(db)

@router.post("/chat")
async def ollama_chat(
    messages: List[Dict[str, str]],
    model: str = "llama2",
    service: AgentService = Depends(get_agent_service)
):
    """Chat with Ollama agent (legacy compatibility)"""
    try:
        response = await service.ollama_chat(messages, model)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/knowledge-builder/chat")
async def knowledge_builder_chat(
    messages: List[Dict[str, str]],
    model: str = "llama2",
    stream: bool = False,
    service: AgentService = Depends(get_agent_service)
):
    """Chat with Knowledge Builder Agent"""
    try:
        result = await service.agent_chat(messages, AgentType.KNOWLEDGE_BUILDER, model, stream)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/modeling/chat")
async def modeling_agent_chat(
    messages: List[Dict[str, str]],
    model: str = "llama2",
    stream: bool = False,
    service: AgentService = Depends(get_agent_service)
):
    """Chat with Modeling/Inference Agent"""
    try:
        if stream:
            async def generate_stream():
                async for chunk in await service.agent_chat(messages, AgentType.MODELING_INFERENCE, model, stream):
                    yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"
            
            return StreamingResponse(
                generate_stream(),
                media_type="text/plain",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
            )
        else:
            result = await service.agent_chat(messages, AgentType.MODELING_INFERENCE, model, stream)
            return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/run")
async def run_agent(
    request: AgentRunRequest,
    service: AgentService = Depends(get_agent_service)
):
    """Run an agent with the specified request"""
    try:
        response = await service.agent_framework.run_agent(request)
        return response.model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/process-document")
async def process_document(
    document_text: str,
    title: str = "Unknown Document",
    authors: List[str] = [],
    bibtex: Optional[str] = None,
    service: AgentService = Depends(get_agent_service)
):
    """Process document using Knowledge Builder Agent"""
    try:
        source_info = {
            "title": title,
            "authors": authors,
            "bibtex": bibtex
        }
        result = await service.process_document(document_text, source_info)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/build-model")
async def build_biological_model(
    organism: str,
    model_type: str,
    parameters: Dict[str, Any] = {},
    service: AgentService = Depends(get_agent_service)
):
    """Build biological model using Modeling Agent"""
    try:
        result = await service.build_model(organism, model_type, parameters)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sessions")
async def list_sessions(
    agent_type: Optional[str] = None,
    service: AgentService = Depends(get_agent_service)
):
    """List agent sessions"""
    try:
        agent_type_enum = None
        if agent_type:
            try:
                agent_type_enum = AgentType(agent_type)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid agent type: {agent_type}")
        
        sessions = await service.list_sessions(agent_type_enum)
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    service: AgentService = Depends(get_agent_service)
):
    """Delete an agent session"""
    try:
        deleted = await service.delete_session(session_id)
        if deleted:
            return {"message": "Session deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/extract-facts")
async def extract_facts(
    text: str,
    model: str = "llama2",
    service: AgentService = Depends(get_agent_service)
):
    """Extract facts from text using Knowledge Builder Agent"""
    try:
        facts = await service.extract_facts(text, model=model)
        return {"facts": facts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/stylize-facts")
async def stylize_facts(
    facts: List[str],
    model: str = "llama2",
    service: AgentService = Depends(get_agent_service)
):
    """Convert facts to stylized facts using Knowledge Builder Agent"""
    try:
        stylized = await service.stylize_facts(facts, model=model)
        return {"stylized_facts": stylized}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tools")
async def list_tools(
    service: AgentService = Depends(get_agent_service)
):
    """List available agent tools"""
    try:
        tools = service.agent_framework.tool_registry.list_tools()
        return {"tools": [tool.model_dump() for tool in tools]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/models")
async def list_ollama_models(
    service: AgentService = Depends(get_agent_service)
):
    """List available Ollama models"""
    try:
        models = await service.list_ollama_models()
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))