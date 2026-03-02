"""
advandeb_kb — AdvanDEB Knowledge Builder library.

Primary API surface used by the Modeling Assistant backend:

    from advandeb_kb import KnowledgeService, IngestionService, VisualizationService
    from advandeb_kb.database.mongodb import get_database
"""

from advandeb_kb.services.knowledge_service import KnowledgeService
from advandeb_kb.services.ingestion_service import IngestionService
from advandeb_kb.services.visualization_service import VisualizationService
from advandeb_kb.services.agent_service import AgentService
from advandeb_kb.services.data_processing_service import DataProcessingService

__all__ = [
    "KnowledgeService",
    "IngestionService",
    "VisualizationService",
    "AgentService",
    "DataProcessingService",
]
