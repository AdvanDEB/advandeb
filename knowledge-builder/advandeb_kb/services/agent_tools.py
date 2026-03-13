"""
Tool system for OpenAI Agents SDK integration.
Provides fact extraction, stylization, knowledge retrieval, and document processing tools.
"""
import json
import logging
import re
from typing import Dict, Any, List, Optional, Callable, Awaitable
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase

from advandeb_kb.models.agent_models import ToolDefinition, ToolCall, ToolResult, KnowledgeNode
from advandeb_kb.services.local_model_provider import LocalModelClient

logger = logging.getLogger(__name__)


class AgentTool:
    """Base class for agent tools"""
    
    def __init__(self, name: str, description: str, input_schema: Dict[str, Any]):
        self.name = name
        self.description = description
        self.input_schema = input_schema
    
    async def execute(self, context: Dict[str, Any], **kwargs) -> Any:
        """Execute the tool with given arguments"""
        raise NotImplementedError("Tool must implement execute method")
    
    def get_definition(self) -> ToolDefinition:
        """Get tool definition for agent"""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema
        )


class FactExtractionTool(AgentTool):
    """Tool for extracting facts from text"""
    
    def __init__(self, model_client: LocalModelClient):
        super().__init__(
            name="extract_facts",
            description="Extract scientific facts from text, focusing on physiology, morphology, anatomy, and bioenergetics",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to extract facts from"},
                    "domain": {"type": "string", "description": "Scientific domain (biology, physiology, etc.)", "default": "biology"}
                },
                "required": ["text"]
            }
        )
        self.model_client = model_client
    
    async def execute(self, context: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Extract facts from text"""
        text = kwargs.get("text", "")
        domain = kwargs.get("domain", "biology")
        
        system_prompt = f"""You are an expert in extracting factual information from scientific texts in {domain}.
        Extract clear, concise facts from the given text. Focus on:
        - Physiological processes and mechanisms
        - Morphological characteristics and structures
        - Anatomical features and organization
        - Bioenergetic relationships and metabolic processes
        - Quantitative data and measurements
        - Species-specific information
        - Environmental interactions
        
        Return each fact as a separate item in a JSON array. Each fact should be:
        - Specific and precise
        - Self-contained
        - Scientifically accurate
        - Include relevant context
        
        Format: ["fact1", "fact2", "fact3", ...]"""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Extract facts from this {domain} text:\n\n{text}"}
        ]
        
        try:
            async with self.model_client as client:
                response = await client.chat.create(
                    model=context.get("model", "llama2"),
                    messages=messages,
                    temperature=0.3
                )
                
                content = response["choices"][0]["message"]["content"]
                
                # Try to parse JSON response
                try:
                    facts = json.loads(content)
                    if isinstance(facts, list):
                        return {"facts": facts, "count": len(facts)}
                    else:
                        return {"facts": [content], "count": 1}
                except json.JSONDecodeError:
                    # Fallback: split by lines and filter
                    facts = [line.strip() for line in content.split('\n') 
                            if line.strip() and not line.strip().startswith('-')]
                    return {"facts": facts[:10], "count": len(facts[:10])}
                    
        except Exception as e:
            logger.error(f"Fact extraction error: {e}")
            return {"facts": [], "count": 0, "error": str(e)}


class FactStylizationTool(AgentTool):
    """Tool for converting facts to stylized facts"""
    
    def __init__(self, model_client: LocalModelClient):
        super().__init__(
            name="stylize_facts",
            description="Convert raw facts into structured, stylized facts with importance ratings and relationships",
            input_schema={
                "type": "object",
                "properties": {
                    "facts": {"type": "array", "items": {"type": "string"}, "description": "List of facts to stylize"},
                    "context": {"type": "string", "description": "Additional context for stylization", "default": ""}
                },
                "required": ["facts"]
            }
        )
        self.model_client = model_client
    
    async def execute(self, context: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Stylize facts with structure and metadata"""
        facts = kwargs.get("facts", [])
        additional_context = kwargs.get("context", "")
        
        system_prompt = """You are an expert in creating structured, stylized facts for biological knowledge graphs.
        Convert each given fact into a structured format with:
        - summary: A concise, standardized version of the fact
        - importance: A score from 0.0 to 1.0 indicating biological significance
        - entities: Key biological entities mentioned (species, organs, molecules, processes)
        - relationships: Potential connections to other biological concepts
        - category: The type of fact (physiological, morphological, anatomical, bioenergetic, ecological)
        - confidence: How certain this fact is (0.0 to 1.0)
        
        Return as a JSON array of objects with this structure:
        {
            "summary": "fact text",
            "importance": 0.8,
            "entities": ["entity1", "entity2"],
            "relationships": ["related_concept1", "related_concept2"],
            "category": "physiological",
            "confidence": 0.9
        }"""
        
        facts_text = "\n".join([f"{i+1}. {fact}" for i, fact in enumerate(facts)])
        if additional_context:
            facts_text = f"Context: {additional_context}\n\nFacts:\n{facts_text}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Stylize these facts:\n\n{facts_text}"}
        ]
        
        try:
            async with self.model_client as client:
                response = await client.chat.create(
                    model=context.get("model", "llama2"),
                    messages=messages,
                    temperature=0.2
                )
                
                content = response["choices"][0]["message"]["content"]
                
                try:
                    stylized = json.loads(content)
                    if isinstance(stylized, list):
                        return {"stylized_facts": stylized, "count": len(stylized)}
                    else:
                        # Fallback structure
                        return {
                            "stylized_facts": [{
                                "summary": fact,
                                "importance": 0.5,
                                "entities": [],
                                "relationships": [],
                                "category": "general",
                                "confidence": 0.5
                            } for fact in facts],
                            "count": len(facts)
                        }
                except json.JSONDecodeError:
                    # Fallback structure
                    return {
                        "stylized_facts": [{
                            "summary": fact,
                            "importance": 0.5,
                            "entities": [],
                            "relationships": [],
                            "category": "general",
                            "confidence": 0.5
                        } for fact in facts],
                        "count": len(facts)
                    }
                    
        except Exception as e:
            logger.error(f"Fact stylization error: {e}")
            return {"stylized_facts": [], "count": 0, "error": str(e)}


class KnowledgeSearchTool(AgentTool):
    """Tool for searching knowledge base"""
    
    def __init__(self, database: AsyncIOMotorDatabase):
        super().__init__(
            name="search_knowledge",
            description="Search the knowledge base for facts, stylized facts, and related information",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "node_types": {"type": "array", "items": {"type": "string"}, "description": "Types of nodes to search", "default": ["fact", "stylized_fact"]},
                    "limit": {"type": "integer", "description": "Maximum number of results", "default": 10}
                },
                "required": ["query"]
            }
        )
        self.db = database
    
    async def execute(self, context: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Search knowledge base"""
        query = kwargs.get("query", "")
        node_types = kwargs.get("node_types", ["fact", "stylized_fact"])
        limit = kwargs.get("limit", 10)
        
        try:
            # Search in knowledge_nodes collection
            collection = self.db["knowledge_nodes"]
            
            # Text search with filters
            search_filter = {
                "node_type": {"$in": node_types},
                "$or": [
                    {"content": {"$regex": query, "$options": "i"}},
                    {"entities": {"$regex": query, "$options": "i"}},
                    {"relationships": {"$regex": query, "$options": "i"}}
                ]
            }
            
            cursor = collection.find(search_filter, {"_id": 0}).limit(limit)
            results = []
            
            async for doc in cursor:
                results.append(doc)
            
            return {
                "results": results,
                "count": len(results),
                "query": query
            }
            
        except Exception as e:
            logger.error(f"Knowledge search error: {e}")
            return {"results": [], "count": 0, "error": str(e)}


class DocumentRetrievalTool(AgentTool):
    """Tool for retrieving documents and their content"""
    
    def __init__(self, database: AsyncIOMotorDatabase):
        super().__init__(
            name="retrieve_document",
            description="Retrieve document content and metadata by ID or search criteria",
            input_schema={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "Document ID to retrieve"},
                    "title_search": {"type": "string", "description": "Search by document title"},
                    "include_content": {"type": "boolean", "description": "Include document content", "default": True}
                }
            }
        )
        self.db = database
    
    async def execute(self, context: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Retrieve document"""
        document_id = kwargs.get("document_id")
        title_search = kwargs.get("title_search")
        include_content = kwargs.get("include_content", True)
        
        try:
            collection = self.db["documents"]
            
            if document_id:
                doc = await collection.find_one({"document_id": document_id}, {"_id": 0})
                if doc:
                    if not include_content:
                        doc.pop("content", None)
                    return {"document": doc, "found": True}
                else:
                    return {"document": None, "found": False}
            
            elif title_search:
                cursor = collection.find(
                    {"title": {"$regex": title_search, "$options": "i"}},
                    {"_id": 0}
                ).limit(5)
                
                docs = []
                async for doc in cursor:
                    if not include_content:
                        doc.pop("content", None)
                    docs.append(doc)
                
                return {"documents": docs, "count": len(docs)}
            
            else:
                return {"error": "Either document_id or title_search must be provided"}
                
        except Exception as e:
            logger.error(f"Document retrieval error: {e}")
            return {"error": str(e)}


class SummarizationTool(AgentTool):
    """Tool for summarizing content"""
    
    def __init__(self, model_client: LocalModelClient):
        super().__init__(
            name="summarize_content",
            description="Summarize large content while preserving key scientific information",
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Content to summarize"},
                    "max_length": {"type": "integer", "description": "Maximum summary length in words", "default": 200},
                    "focus": {"type": "string", "description": "Specific focus area for summary", "default": "key findings"}
                },
                "required": ["content"]
            }
        )
        self.model_client = model_client
    
    async def execute(self, context: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Summarize content"""
        content = kwargs.get("content", "")
        max_length = kwargs.get("max_length", 200)
        focus = kwargs.get("focus", "key findings")
        
        system_prompt = f"""You are an expert at summarizing scientific content while preserving essential information.
        Create a concise summary focusing on {focus}. The summary should:
        - Be approximately {max_length} words or less
        - Preserve key scientific facts and data
        - Maintain technical accuracy
        - Include important quantitative information
        - Highlight main conclusions and implications
        
        Format the summary as clear, structured text."""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Summarize this content:\n\n{content}"}
        ]
        
        try:
            async with self.model_client as client:
                response = await client.chat.create(
                    model=context.get("model", "llama2"),
                    messages=messages,
                    temperature=0.3
                )
                
                summary = response["choices"][0]["message"]["content"]
                word_count = len(summary.split())
                
                return {
                    "summary": summary,
                    "word_count": word_count,
                    "original_length": len(content.split()),
                    "compression_ratio": round(word_count / len(content.split()), 2) if content else 0
                }
                
        except Exception as e:
            logger.error(f"Summarization error: {e}")
            return {"summary": "", "error": str(e)}


class TaxonLookupTool(AgentTool):
    """Look up an organism name in the NCBI taxonomy database."""

    def __init__(self):
        super().__init__(
            name="lookup_taxon",
            description="Look up an organism's scientific or common name in the NCBI taxonomy. Returns tax_id, rank, and canonical name if found.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Scientific or common name of the organism (e.g. 'Salmo trutta', 'brown trout')"
                    }
                },
                "required": ["name"]
            }
        )

    async def execute(self, context: Dict[str, Any], **kwargs) -> Any:
        name = kwargs.get("name", "").strip()
        if not name:
            return {"found": False, "name": name, "reason": "empty name"}
        db = context.get("db")
        if db is None:
            return {"found": False, "name": name, "reason": "no db context"}

        taxon = await db.taxonomy_nodes.find_one(
            {"$or": [
                {"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}},
                {"synonyms": {"$regex": f"^{re.escape(name)}$", "$options": "i"}},
                {"common_names": {"$regex": f"^{re.escape(name)}$", "$options": "i"}},
            ]},
            {"tax_id": 1, "name": 1, "rank": 1}
        )
        if taxon:
            return {
                "found": True,
                "tax_id": taxon["tax_id"],
                "name": taxon["name"],
                "rank": taxon.get("rank", "no rank"),
            }
        return {"found": False, "name": name}


class ToolRegistry:
    """Registry for managing agent tools"""
    
    def __init__(self, database: AsyncIOMotorDatabase, model_client: LocalModelClient):
        self.db = database
        self.model_client = model_client
        self.tools: Dict[str, AgentTool] = {}
        self._register_default_tools()
    
    def _register_default_tools(self):
        """Register default tools"""
        self.register_tool(FactExtractionTool(self.model_client))
        self.register_tool(FactStylizationTool(self.model_client))
        self.register_tool(KnowledgeSearchTool(self.db))
        self.register_tool(DocumentRetrievalTool(self.db))
        self.register_tool(SummarizationTool(self.model_client))
        self.register_tool(TaxonLookupTool())
    
    def register_tool(self, tool: AgentTool):
        """Register a tool"""
        self.tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")
    
    def get_tool(self, name: str) -> Optional[AgentTool]:
        """Get tool by name"""
        return self.tools.get(name)
    
    def list_tools(self) -> List[ToolDefinition]:
        """List all available tools"""
        return [tool.get_definition() for tool in self.tools.values()]
    
    async def execute_tool(self, tool_call: ToolCall, context: Dict[str, Any]) -> ToolResult:
        """Execute a tool call"""
        tool = self.get_tool(tool_call.tool_name)
        if not tool:
            return ToolResult(
                call_id=tool_call.call_id,
                result=None,
                success=False,
                error_message=f"Unknown tool: {tool_call.tool_name}"
            )
        
        try:
            result = await tool.execute(context, **tool_call.arguments)
            return ToolResult(
                call_id=tool_call.call_id,
                result=result,
                success=True
            )
        except Exception as e:
            logger.error(f"Tool execution error for {tool_call.tool_name}: {e}")
            return ToolResult(
                call_id=tool_call.call_id,
                result=None,
                success=False,
                error_message=str(e)
            )