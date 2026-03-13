"""
Celery tasks for knowledge-graph document-taxon linking.

Each task processes a batch of documents from the documents collection
and writes matches to document_taxon_relations.

The task runs in three phases:
  1. Build name index for the requested taxonomy subtree
  2. Process a slice of documents (skip/limit)
  3. Return a summary dict

Trigger via API (POST /api/kg/link) or directly:
    from tasks.kg_tasks import link_batch
    link_batch.delay(root_taxid=40674, limit=1000, skip=0)
"""
import asyncio
import logging
from typing import Optional

from celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="kg_tasks.link_batch")
def link_batch(
    self,
    root_taxid: Optional[int] = 40674,
    limit: int = 1000,
    skip: int = 0,
    overwrite: bool = False,
) -> dict:
    """Link a batch of documents to taxonomy nodes.

    Args:
        root_taxid: NCBI taxonomy ID to restrict the name index to.
                    None = full taxonomy (slow / large).
        limit:      Documents to process in this task.
        skip:       Offset into documents collection.
        overwrite:  Re-link already-linked documents.

    Returns:
        Summary dict from KGBuilderService.link_documents().
    """
    return asyncio.run(_run(root_taxid, limit, skip, overwrite))


@celery_app.task(bind=True, name="kg_tasks.link_batch_agent")
def link_batch_agent(
    self,
    model: str = "mistral",
    limit: int = 500,
    skip: int = 0,
    overwrite: bool = False,
) -> dict:
    """Link documents to taxonomy nodes using the LLM agent.

    Args:
        model:     Ollama model name.
        limit:     Documents to process in this task.
        skip:      Offset into documents collection.
        overwrite: Re-link already-linked documents.

    Returns:
        Summary dict from KGLinkerAgentService.link_documents().
    """
    return asyncio.run(_run_agent(model, limit, skip, overwrite))


async def _run_agent(model: str, limit: int, skip: int, overwrite: bool) -> dict:
    from advandeb_kb.database.mongodb import mongodb
    from advandeb_kb.services.kg_linker_agent_service import KGLinkerAgentService

    await mongodb.connect()
    try:
        svc = KGLinkerAgentService(mongodb.database)
        return await svc.link_documents(model=model, limit=limit, skip=skip, overwrite=overwrite)
    finally:
        await mongodb.disconnect()


async def _run(
    root_taxid: Optional[int],
    limit: int,
    skip: int,
    overwrite: bool,
) -> dict:
    from advandeb_kb.database.mongodb import mongodb
    from advandeb_kb.services.kg_builder_service import KGBuilderService

    await mongodb.connect()
    try:
        db = mongodb.database
        service = KGBuilderService(db)
        await service.ensure_indexes()
        n_indexed = await service.build_name_index(root_taxid=root_taxid)
        logger.info("Name index: %d entries (root_taxid=%s)", n_indexed, root_taxid)
        result = await service.link_documents(limit=limit, skip=skip, overwrite=overwrite)
        result["index_entries"] = n_indexed
        result["root_taxid"] = root_taxid
        return result
    finally:
        await mongodb.disconnect()
