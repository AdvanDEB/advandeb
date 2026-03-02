import httpx
from typing import List, Dict, Any, AsyncIterator
from advandeb_kb.config.settings import settings
import json
import logging

from advandeb_kb.services.agent_framework import AgentFramework
from advandeb_kb.services.local_model_provider import LocalModelClient
from advandeb_kb.models.agent_models import AgentType, AgentRunRequest, AgentRunResponse

logger = logging.getLogger(__name__)

class AgentService:
    def __init__(self, database):
        self.db = database
        self.ollama_base_url = settings.OLLAMA_BASE_URL
        self.agent_framework = AgentFramework(database)
        self.model_client = LocalModelClient()

    async def ollama_chat(self, messages: List[Dict[str, str]], model: str = "llama2") -> str:
        """Chat with Ollama model (legacy compatibility)"""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self.ollama_base_url}/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": False
                    },
                    timeout=60.0
                )
                response.raise_for_status()
                return response.json()["message"]["content"]
            except Exception as e:
                logger.error(f"Ollama chat error: {e}")
                raise

    async def extract_facts(self, text: str, model: str = "llama2") -> List[str]:
        """Extract facts using Knowledge Builder Agent"""
        try:
            # Use the Knowledge Builder agent for fact extraction
            request = AgentRunRequest(
                agent_type=AgentType.KNOWLEDGE_BUILDER,
                message=f"Please extract scientific facts from this text: {text}",
                model=model,
                enable_tools=True,
                max_tool_calls=5
            )
            
            response = await self.agent_framework.run_agent(request)
            
            # Extract facts from tool results
            facts = []
            for step in response.steps:
                if (step.step_type == "tool_result" and 
                    isinstance(step.content, dict) and 
                    step.content.get("success")):
                    
                    result = step.content.get("result", {})
                    if "facts" in result:
                        facts.extend(result["facts"])
            
            return facts if facts else [response.response]
            
        except Exception as e:
            logger.error(f"Fact extraction error: {e}")
            # Fallback to direct model call
            return await self._legacy_extract_facts(text, model)

    async def _legacy_extract_facts(self, text: str, model: str = "llama2") -> List[str]:
        """Legacy fact extraction method as fallback"""
        system_prompt = """You are an expert in extracting factual information from scientific and biological texts. 
        Extract clear, concise facts from the given text. Focus on:
        - Physiological processes
        - Morphological characteristics
        - Anatomical structures
        - Bioenergetic relationships
        - Quantitative data
        
        Return each fact as a separate item in a JSON array."""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Extract facts from this text:\n\n{text}"}
        ]
        
        try:
            response = await self.ollama_chat(messages, model=model)
            
            # Try to parse JSON response
            try:
                facts = json.loads(response)
                if isinstance(facts, list):
                    return facts
                else:
                    return [response]  # Fallback to single fact
            except json.JSONDecodeError:
                # If not JSON, split by lines and filter
                facts = [line.strip() for line in response.split('\n') if line.strip() and not line.strip().startswith('-')]
                return facts[:10]  # Limit to 10 facts
                
        except Exception as e:
            logger.error(f"Legacy fact extraction error: {e}")
            return []

    async def stylize_facts(self, facts: List[str], model: str = "llama2") -> List[Dict[str, Any]]:
        """Stylize facts using Knowledge Builder Agent"""
        try:
            # Use the Knowledge Builder agent for fact stylization
            facts_text = "\n".join([f"{i+1}. {fact}" for i, fact in enumerate(facts)])
            request = AgentRunRequest(
                agent_type=AgentType.KNOWLEDGE_BUILDER,
                message=f"Please stylize these facts for the knowledge graph: {facts_text}",
                model=model,
                enable_tools=True,
                max_tool_calls=5
            )
            
            response = await self.agent_framework.run_agent(request)
            
            # Extract stylized facts from tool results
            stylized_facts = []
            for step in response.steps:
                if (step.step_type == "tool_result" and 
                    isinstance(step.content, dict) and 
                    step.content.get("success")):
                    
                    result = step.content.get("result", {})
                    if "stylized_facts" in result:
                        stylized_facts.extend(result["stylized_facts"])
            
            return stylized_facts if stylized_facts else self._create_fallback_stylized_facts(facts)
            
        except Exception as e:
            logger.error(f"Fact stylization error: {e}")
            # Fallback to legacy method
            return await self._legacy_stylize_facts(facts, model)

    def _create_fallback_stylized_facts(self, facts: List[str]) -> List[Dict[str, Any]]:
        """Create fallback stylized facts structure"""
        return [{
            "summary": fact,
            "importance": 0.5,
            "relationships": [],
            "entities": [],
            "category": "general",
            "confidence": 0.5
        } for fact in facts]

    async def _legacy_stylize_facts(self, facts: List[str], model: str = "llama2") -> List[Dict[str, Any]]:
        """Legacy fact stylization method as fallback"""
        system_prompt = """You are an expert in creating structured, stylized facts for knowledge graphs.
        Convert each given fact into a structured format with:
        - summary: A concise version of the fact
        - importance: A score from 0.0 to 1.0 indicating the importance
        - relationships: Potential connections to other concepts
        - entities: Key entities mentioned in the fact
        
        Return as a JSON array of objects."""
        
        facts_text = "\n".join([f"{i+1}. {fact}" for i, fact in enumerate(facts)])
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Stylize these facts:\n\n{facts_text}"}
        ]
        
        try:
            response = await self.ollama_chat(messages, model=model)
            
            # Try to parse JSON response
            try:
                stylized = json.loads(response)
                if isinstance(stylized, list):
                    return stylized
                else:
                    # Fallback to basic structure
                    return self._create_fallback_stylized_facts(facts)
            except json.JSONDecodeError:
                # Fallback to basic structure
                return self._create_fallback_stylized_facts(facts)
                
        except Exception as e:
            logger.error(f"Legacy fact stylization error: {e}")
            return self._create_fallback_stylized_facts(facts)

    async def agent_chat(self, messages: List[Dict[str, str]], agent_type: AgentType, model: str = "llama2", stream: bool = False) -> Any:
        """Chat with specific agent type"""
        if not messages:
            return {"response": "No messages provided"}
        
        # Get the last user message
        user_message = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break
        
        request = AgentRunRequest(
            agent_type=agent_type,
            message=user_message,
            model=model,
            enable_tools=True,
            max_tool_calls=10,
            stream=stream
        )
        
        if stream and agent_type == AgentType.MODELING_INFERENCE:
            # Return streaming response for modeling agent
            return self.agent_framework.modeling_agent.stream_chat(request)
        else:
            # Regular response
            response = await self.agent_framework.run_agent(request)
            return {
                "response": response.response,
                "session_id": response.session_id,
                "tool_calls": [tc.model_dump() for tc in response.tool_calls],
                "reasoning_path": response.reasoning_path,
                "context_nodes": response.context_nodes
            }

    async def process_document(self, document_text: str, source_info: Dict[str, Any]) -> Dict[str, Any]:
        """Process document using Knowledge Builder Agent"""
        return await self.agent_framework.knowledge_builder.process_document(document_text, source_info)

    async def build_model(self, organism: str, model_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Build biological model using Modeling Agent"""
        return await self.agent_framework.modeling_agent.build_model(organism, model_type, parameters)

    async def list_sessions(self, agent_type: AgentType = None) -> List[Dict[str, Any]]:
        """List agent sessions"""
        return await self.agent_framework.list_sessions(agent_type)

    async def delete_session(self, session_id: str) -> bool:
        """Delete agent session"""
        return await self.agent_framework.delete_session(session_id)

    async def list_ollama_models(self) -> List[str]:
        """List available Ollama models"""
        async with self.model_client as client:
            try:
                models_data = await client.list_models()
                return [model["id"] for model in models_data["data"]]
            except Exception as e:
                logger.error(f"Error listing Ollama models: {e}")
                # Fallback to direct API call
                async with httpx.AsyncClient() as http_client:
                    try:
                        response = await http_client.get(f"{self.ollama_base_url}/api/tags")
                        response.raise_for_status()
                        data = response.json()
                        return [model["name"] for model in data.get("models", [])]
                    except Exception as e2:
                        logger.error(f"Error in fallback model listing: {e2}")
                        return ["llama2", "mistral"]  # Default models