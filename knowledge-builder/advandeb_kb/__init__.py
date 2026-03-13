"""
advandeb_kb — AdvanDEB Knowledge Builder library.

Primary API surface used by the Modeling Assistant backend:

    from advandeb_kb import KnowledgeService, IngestionService, TaxonomyService
    from advandeb_kb.database.mongodb import get_database
"""

from advandeb_kb.services.knowledge_service import KnowledgeService
from advandeb_kb.services.ingestion_service import IngestionService
from advandeb_kb.services.agent_service import AgentService
from advandeb_kb.services.data_processing_service import DataProcessingService
from advandeb_kb.services.taxonomy_service import TaxonomyService
from advandeb_kb.services.graph_builder_service import GraphBuilderService
from advandeb_kb.services.kg_linker_agent_service import KGLinkerAgentService
from advandeb_kb.models.knowledge import DocumentTaxonRelation

# RAG / vector search stack (Week 1-3)
from advandeb_kb.services.embedding_service import EmbeddingService
from advandeb_kb.services.chromadb_service import ChromaDBService
from advandeb_kb.services.chunking_service import ChunkingService, Chunk
from advandeb_kb.services.hybrid_retrieval_service import (
    HybridRetrievalService,
    RetrievalResult,
)
from advandeb_kb.database.arango_client import ArangoDatabase

# Graph expansion & provenance (Week 4)
from advandeb_kb.services.graph_expansion_service import GraphExpansionService
from advandeb_kb.models.provenance import (
    ProvenanceTrace,
    RetrievalContext,
    GraphPathStep,
)

# Cache service (Week 11)
from advandeb_kb.services.cache_service import CacheService

# MCP protocol (Week 5)
from advandeb_kb.mcp.protocol import MCPServer, MCPClient

# Agent network (Weeks 5-10)
from advandeb_kb.agents.base_agent import BaseAgent
from advandeb_kb.agents.retrieval_agent import RetrievalAgent
from advandeb_kb.agents.graph_explorer_agent import GraphExplorerAgent
from advandeb_kb.agents.synthesis_agent import SynthesisAgent
from advandeb_kb.agents.query_planner_agent import QueryPlannerAgent
from advandeb_kb.agents.curator_agent import CuratorAgent

__all__ = [
    # Core KB services
    "KnowledgeService",
    "IngestionService",
    "AgentService",
    "DataProcessingService",
    "TaxonomyService",
    "GraphBuilderService",
    "KGLinkerAgentService",
    "DocumentTaxonRelation",
    # RAG / vector stack
    "EmbeddingService",
    "ChromaDBService",
    "ChunkingService",
    "Chunk",
    "HybridRetrievalService",
    "RetrievalResult",
    "ArangoDatabase",
    # Graph expansion & provenance
    "GraphExpansionService",
    "ProvenanceTrace",
    "RetrievalContext",
    "GraphPathStep",
    # Cache
    "CacheService",
    # MCP protocol
    "MCPServer",
    "MCPClient",
    # Agent network
    "BaseAgent",
    "RetrievalAgent",
    "GraphExplorerAgent",
    "SynthesisAgent",
    "QueryPlannerAgent",
    "CuratorAgent",
]
