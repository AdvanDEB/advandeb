"""
Agent framework models for OpenAI Agents SDK integration with local Ollama models.
"""
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Union
from enum import Enum
import uuid
from datetime import datetime


class AgentType(str, Enum):
    """Types of agents available in the system"""
    KNOWLEDGE_BUILDER = "knowledge_builder"
    MODELING_INFERENCE = "modeling_inference"


class ToolDefinition(BaseModel):
    """Definition of a tool that agents can use"""
    name: str
    description: str
    input_schema: Dict[str, Any] = Field(
        default_factory=dict,
        description="JSON schema describing expected input parameters"
    )
    enabled: bool = True


class ToolCall(BaseModel):
    """A tool call made by an agent"""
    tool_name: str
    arguments: Dict[str, Any]
    call_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class ToolResult(BaseModel):
    """Result of a tool execution"""
    call_id: str
    result: Any
    success: bool = True
    error_message: Optional[str] = None


class AgentMessage(BaseModel):
    """Message in an agent conversation"""
    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_calls: List[ToolCall] = Field(default_factory=list)
    tool_results: List[ToolResult] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AgentSession(BaseModel):
    """Agent conversation session"""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_type: AgentType
    model: str = "llama2"
    messages: List[AgentMessage] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AgentRunRequest(BaseModel):
    """Request to run an agent"""
    session_id: Optional[str] = None
    agent_type: AgentType
    message: str
    model: str = "llama2"
    enable_tools: bool = True
    max_tool_calls: int = 10
    stream: bool = False


class AgentRunStep(BaseModel):
    """A step in agent execution"""
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    step_type: str  # "message", "tool_call", "tool_result"
    content: Any
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class AgentRunResponse(BaseModel):
    """Response from agent execution"""
    session_id: str
    response: str
    steps: List[AgentRunStep] = Field(default_factory=list)
    tool_calls: List[ToolCall] = Field(default_factory=list)
    reasoning_path: List[str] = Field(default_factory=list)
    context_nodes: List[str] = Field(default_factory=list)  # KB nodes accessed
    completed: bool = True


class KnowledgeNode(BaseModel):
    """A node in the knowledge graph"""
    node_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    node_type: str  # "fact", "stylized_fact", "summary", "document"
    entities: List[str] = Field(default_factory=list)
    relationships: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    bibtex: Optional[str] = None
    importance: float = 0.5
    confidence: float = 0.5
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RAGContext(BaseModel):
    """RAG context for agent operations"""
    query: str
    retrieved_nodes: List[KnowledgeNode] = Field(default_factory=list)
    context_summary: str = ""
    relevance_scores: List[float] = Field(default_factory=list)


class AgentConfig(BaseModel):
    """Configuration for an agent"""
    agent_type: AgentType
    system_prompt: str
    available_tools: List[str] = Field(default_factory=list)
    max_context_length: int = 4000
    temperature: float = 0.7
    enable_rag: bool = True
    rag_top_k: int = 5