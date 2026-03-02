"""
Main agent framework that integrates OpenAI Agents SDK with local Ollama models.
Implements Knowledge Builder and Modeling/Inference agents.
"""
import json
import asyncio
from typing import Dict, Any, List, Optional, AsyncIterator
from datetime import datetime
import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from advandeb_kb.models.agent_models import (
    AgentType, AgentSession, AgentMessage, AgentRunRequest, AgentRunResponse,
    AgentRunStep, ToolCall, KnowledgeNode, RAGContext, AgentConfig
)
from advandeb_kb.services.local_model_provider import LocalModelClient
from advandeb_kb.services.agent_tools import ToolRegistry

logger = logging.getLogger(__name__)


class BaseAgent:
    """Base class for all agents"""
    
    def __init__(
        self,
        agent_type: AgentType,
        database: AsyncIOMotorDatabase,
        model_client: LocalModelClient,
        tool_registry: ToolRegistry,
        config: AgentConfig
    ):
        self.agent_type = agent_type
        self.db = database
        self.model_client = model_client
        self.tool_registry = tool_registry
        self.config = config
    
    async def create_session(self, initial_message: str = None) -> AgentSession:
        """Create a new agent session"""
        session = AgentSession(
            agent_type=self.agent_type,
            context={"created_by": self.agent_type.value}
        )
        
        if initial_message:
            session.messages.append(AgentMessage(
                role="user",
                content=initial_message
            ))
        
        # Save session to database
        await self.db["agent_sessions"].insert_one(session.model_dump())
        return session
    
    async def load_session(self, session_id: str) -> Optional[AgentSession]:
        """Load an existing session"""
        doc = await self.db["agent_sessions"].find_one({"session_id": session_id})
        if doc:
            doc.pop("_id", None)
            return AgentSession(**doc)
        return None
    
    async def save_session(self, session: AgentSession):
        """Save session to database"""
        session.updated_at = datetime.utcnow()
        await self.db["agent_sessions"].update_one(
            {"session_id": session.session_id},
            {"$set": session.model_dump()},
            upsert=True
        )
    
    async def run(
        self,
        request: AgentRunRequest,
        session: AgentSession = None
    ) -> AgentRunResponse:
        """Run the agent with a request"""
        if not session:
            session = await self.load_session(request.session_id) if request.session_id else None
            if not session:
                session = await self.create_session()
        
        # Add user message
        session.messages.append(AgentMessage(
            role="user",
            content=request.message
        ))
        
        # Build system message with tools
        system_message = self._build_system_message()
        
        # Prepare messages for model
        messages = [{"role": "system", "content": system_message}]
        for msg in session.messages[-10:]:  # Last 10 messages for context
            messages.append({
                "role": msg.role,
                "content": msg.content
            })
        
        # Execute agent loop
        response = await self._execute_agent_loop(
            messages=messages,
            session=session,
            request=request
        )
        
        # Save session
        await self.save_session(session)
        
        return response
    
    def _build_system_message(self) -> str:
        """Build system message with agent role and available tools"""
        system_prompt = self.config.system_prompt
        
        if self.config.available_tools:
            tools_info = "Available tools:\n"
            for tool_name in self.config.available_tools:
                tool = self.tool_registry.get_tool(tool_name)
                if tool:
                    tools_info += f"- {tool.name}: {tool.description}\n"
            
            system_prompt += f"\n\n{tools_info}"
            system_prompt += "\nTo use a tool, respond with JSON: {\"tool\": \"tool_name\", \"arguments\": {...}}"
        
        return system_prompt
    
    async def _execute_agent_loop(
        self,
        messages: List[Dict[str, str]],
        session: AgentSession,
        request: AgentRunRequest
    ) -> AgentRunResponse:
        """Execute the main agent reasoning loop with tool calls"""
        steps = []
        tool_calls = []
        reasoning_path = []
        context_nodes = []
        
        current_messages = messages.copy()
        tool_call_count = 0
        
        while tool_call_count < request.max_tool_calls:
            # Get model response
            try:
                async with self.model_client as client:
                    response = await client.chat.create(
                        model=request.model,
                        messages=current_messages,
                        temperature=self.config.temperature
                    )
                
                content = response["choices"][0]["message"]["content"]
                
                # Log reasoning step
                steps.append(AgentRunStep(
                    step_type="message",
                    content={"role": "assistant", "content": content}
                ))
                
                # Check if this is a tool call
                tool_call = self._parse_tool_call(content)
                
                if not tool_call:
                    # Regular response, end loop
                    session.messages.append(AgentMessage(
                        role="assistant",
                        content=content
                    ))
                    
                    return AgentRunResponse(
                        session_id=session.session_id,
                        response=content,
                        steps=steps,
                        tool_calls=tool_calls,
                        reasoning_path=reasoning_path,
                        context_nodes=context_nodes,
                        completed=True
                    )
                
                # Execute tool call
                tool_calls.append(tool_call)
                tool_call_count += 1
                
                steps.append(AgentRunStep(
                    step_type="tool_call",
                    content=tool_call.model_dump()
                ))
                
                # Execute tool
                tool_result = await self.tool_registry.execute_tool(
                    tool_call,
                    {"model": request.model, "session_id": session.session_id}
                )
                
                steps.append(AgentRunStep(
                    step_type="tool_result",
                    content=tool_result.model_dump()
                ))
                
                # Add tool interaction to messages
                current_messages.append({"role": "assistant", "content": content})
                current_messages.append({
                    "role": "tool",
                    "content": f"Tool {tool_call.tool_name} result: {json.dumps(tool_result.result, ensure_ascii=False)}"
                })
                
                # Update reasoning path and context
                reasoning_path.append(f"Used {tool_call.tool_name}")
                if tool_call.tool_name == "search_knowledge" and tool_result.success:
                    result_data = tool_result.result
                    if isinstance(result_data, dict) and "results" in result_data:
                        for node in result_data["results"]:
                            if "node_id" in node:
                                context_nodes.append(node["node_id"])
                
            except Exception as e:
                logger.error(f"Agent execution error: {e}")
                return AgentRunResponse(
                    session_id=session.session_id,
                    response=f"Error during agent execution: {str(e)}",
                    steps=steps,
                    tool_calls=tool_calls,
                    reasoning_path=reasoning_path,
                    context_nodes=context_nodes,
                    completed=False
                )
        
        # If we get here, we hit the tool call limit
        final_response = "I've reached the maximum number of tool calls. Let me provide a summary based on what I've found."
        
        # Try to get a final summary
        try:
            current_messages.append({
                "role": "user",
                "content": "Please provide a summary of your findings without using any tools."
            })
            
            async with self.model_client as client:
                response = await client.chat.create(
                    model=request.model,
                    messages=current_messages,
                    temperature=self.config.temperature
                )
            
            final_response = response["choices"][0]["message"]["content"]
            
        except Exception as e:
            logger.error(f"Final summary error: {e}")
        
        session.messages.append(AgentMessage(
            role="assistant",
            content=final_response
        ))
        
        return AgentRunResponse(
            session_id=session.session_id,
            response=final_response,
            steps=steps,
            tool_calls=tool_calls,
            reasoning_path=reasoning_path,
            context_nodes=context_nodes,
            completed=True
        )
    
    def _parse_tool_call(self, content: str) -> Optional[ToolCall]:
        """Parse potential tool call from model response"""
        try:
            content = content.strip()
            if content.startswith("{") and content.endswith("}"):
                data = json.loads(content)
                if "tool" in data and "arguments" in data:
                    return ToolCall(
                        tool_name=data["tool"],
                        arguments=data["arguments"]
                    )
        except json.JSONDecodeError:
            pass
        return None


class KnowledgeBuilderAgent(BaseAgent):
    """Agent for building knowledge base from literature"""
    
    def __init__(self, database: AsyncIOMotorDatabase, model_client: LocalModelClient, tool_registry: ToolRegistry):
        config = AgentConfig(
            agent_type=AgentType.KNOWLEDGE_BUILDER,
            system_prompt="""You are an expert knowledge builder agent specializing in scientific literature analysis and knowledge graph construction.

Your primary responsibilities:
1. Ingest and analyze scientific literature
2. Extract factual information focusing on physiology, morphology, anatomy, and bioenergetics
3. Create stylized facts with proper metadata and relationships
4. Build knowledge graphs showing connections between facts
5. Document sources in bibtex format
6. Suggest new knowledge nodes and relationships

You work systematically:
- First extract raw facts from literature
- Then stylize facts with importance ratings and entity relationships
- Store facts with proper provenance and source documentation
- Build networks showing relationships between facts, taxonomic connections, and causal relationships
- Suggest areas where knowledge is incomplete or needs verification

Always maintain scientific rigor and provide proper attribution for all information.""",
            available_tools=["extract_facts", "stylize_facts", "search_knowledge", "retrieve_document", "summarize_content"],
            enable_rag=True,
            rag_top_k=10
        )
        super().__init__(AgentType.KNOWLEDGE_BUILDER, database, model_client, tool_registry, config)
    
    async def process_document(self, document_text: str, source_info: Dict[str, Any]) -> Dict[str, Any]:
        """Process a document and extract knowledge"""
        # Create a specialized request for document processing
        request = AgentRunRequest(
            agent_type=AgentType.KNOWLEDGE_BUILDER,
            message=f"Please analyze this scientific document and extract relevant knowledge:\n\n{document_text}",
            enable_tools=True,
            max_tool_calls=15
        )
        
        response = await self.run(request)
        
        # Store extracted knowledge nodes
        knowledge_nodes = []
        for step in response.steps:
            if (step.step_type == "tool_result" and 
                isinstance(step.content, dict) and 
                step.content.get("success") and
                "stylized_facts" in step.content.get("result", {})):
                
                stylized_facts = step.content["result"]["stylized_facts"]
                for fact in stylized_facts:
                    node = KnowledgeNode(
                        content=fact["summary"],
                        node_type="stylized_fact",
                        entities=fact.get("entities", []),
                        relationships=fact.get("relationships", []),
                        sources=[source_info.get("title", "unknown")],
                        bibtex=source_info.get("bibtex"),
                        importance=fact.get("importance", 0.5),
                        confidence=fact.get("confidence", 0.5),
                        metadata={
                            "category": fact.get("category", "general"),
                            "source_info": source_info
                        }
                    )
                    knowledge_nodes.append(node)
        
        # Save knowledge nodes to database
        if knowledge_nodes:
            await self.db["knowledge_nodes"].insert_many([node.model_dump() for node in knowledge_nodes])
        
        return {
            "processed": True,
            "knowledge_nodes_created": len(knowledge_nodes),
            "response": response.response,
            "reasoning_path": response.reasoning_path
        }


class ModelingInferenceAgent(BaseAgent):
    """Agent for modeling organisms and inferencing from knowledge base"""
    
    def __init__(self, database: AsyncIOMotorDatabase, model_client: LocalModelClient, tool_registry: ToolRegistry):
        config = AgentConfig(
            agent_type=AgentType.MODELING_INFERENCE,
            system_prompt="""You are an expert modeling and inference agent specializing in building individual-based models from biological knowledge.

Your primary responsibilities:
1. Query and traverse the knowledge base to find relevant facts and stylized facts
2. Build bioenergetic models for organisms based on available knowledge
3. Create individual-based models incorporating physiological, morphological, and anatomical data
4. Provide interactive consultation on biological processes and relationships
5. Identify knowledge gaps and suggest areas for further research
6. Explain complex biological systems using evidence from the knowledge base

You approach problems systematically:
- Search the knowledge base for relevant information
- Analyze relationships between facts and concepts
- Build comprehensive models incorporating multiple data sources
- Validate models against known biological principles
- Provide clear explanations with proper citations
- Suggest improvements or additional data needs

You maintain scientific accuracy while making complex information accessible.""",
            available_tools=["search_knowledge", "retrieve_document", "summarize_content"],
            enable_rag=True,
            rag_top_k=15,
            temperature=0.4
        )
        super().__init__(AgentType.MODELING_INFERENCE, database, model_client, tool_registry, config)
    
    async def build_model(self, organism: str, model_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Build a biological model for an organism"""
        request = AgentRunRequest(
            agent_type=AgentType.MODELING_INFERENCE,
            message=f"Build a {model_type} model for {organism} using available knowledge. Parameters: {json.dumps(parameters)}",
            enable_tools=True,
            max_tool_calls=20
        )
        
        response = await self.run(request)
        
        return {
            "model_built": True,
            "organism": organism,
            "model_type": model_type,
            "parameters": parameters,
            "response": response.response,
            "knowledge_nodes_used": response.context_nodes,
            "reasoning_path": response.reasoning_path
        }
    
    async def stream_chat(self, request: AgentRunRequest) -> AsyncIterator[Dict[str, Any]]:
        """Stream chat responses for interactive inference"""
        # For streaming, we'll implement a simpler approach
        # that yields intermediate results
        
        session = None
        if request.session_id:
            session = await self.load_session(request.session_id)
        if not session:
            session = await self.create_session()
        
        yield {"type": "session_start", "session_id": session.session_id}
        
        # Add user message
        session.messages.append(AgentMessage(
            role="user",
            content=request.message
        ))
        
        yield {"type": "user_message", "content": request.message}
        
        # Build system message
        system_message = self._build_system_message()
        messages = [{"role": "system", "content": system_message}]
        
        # Add conversation history
        for msg in session.messages[-10:]:
            messages.append({"role": msg.role, "content": msg.content})
        
        # Get streaming response
        try:
            async with self.model_client as client:
                response_stream = await client.chat.create(
                    model=request.model,
                    messages=messages,
                    stream=True,
                    temperature=self.config.temperature
                )
                
                full_response = ""
                async for chunk in response_stream:
                    if "choices" in chunk and chunk["choices"]:
                        delta = chunk["choices"][0].get("delta", {})
                        if "content" in delta:
                            content = delta["content"]
                            full_response += content
                            yield {"type": "token", "content": content}
                
                # Save complete response
                session.messages.append(AgentMessage(
                    role="assistant",
                    content=full_response
                ))
                
                await self.save_session(session)
                
                yield {"type": "complete", "full_response": full_response}
                
        except Exception as e:
            logger.error(f"Streaming chat error: {e}")
            yield {"type": "error", "error": str(e)}


class AgentFramework:
    """Main framework for managing agents"""
    
    def __init__(self, database: AsyncIOMotorDatabase):
        self.db = database
        self.model_client = LocalModelClient()
        self.tool_registry = ToolRegistry(database, self.model_client)
        
        # Initialize agents
        self.knowledge_builder = KnowledgeBuilderAgent(database, self.model_client, self.tool_registry)
        self.modeling_agent = ModelingInferenceAgent(database, self.model_client, self.tool_registry)
        
        self.agents = {
            AgentType.KNOWLEDGE_BUILDER: self.knowledge_builder,
            AgentType.MODELING_INFERENCE: self.modeling_agent
        }
    
    def get_agent(self, agent_type: AgentType) -> BaseAgent:
        """Get agent by type"""
        return self.agents.get(agent_type)
    
    async def run_agent(self, request: AgentRunRequest) -> AgentRunResponse:
        """Run an agent with the given request"""
        agent = self.get_agent(request.agent_type)
        if not agent:
            raise ValueError(f"Unknown agent type: {request.agent_type}")
        
        return await agent.run(request)
    
    async def list_sessions(self, agent_type: AgentType = None) -> List[Dict[str, Any]]:
        """List agent sessions"""
        filter_dict = {}
        if agent_type:
            filter_dict["agent_type"] = agent_type.value
        
        cursor = self.db["agent_sessions"].find(filter_dict, {"_id": 0})
        sessions = []
        async for doc in cursor:
            sessions.append(doc)
        
        return sessions
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete an agent session"""
        result = await self.db["agent_sessions"].delete_one({"session_id": session_id})
        return result.deleted_count > 0