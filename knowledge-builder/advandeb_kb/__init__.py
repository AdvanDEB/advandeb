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

__all__ = [
    "KnowledgeService",
    "IngestionService",
    "AgentService",
    "DataProcessingService",
    "TaxonomyService",
    "GraphBuilderService",
]
