"""
DataProcessingService — text extraction from PDFs and web pages.

All I/O is async-safe: PDF reading is offloaded to a thread pool via
asyncio.to_thread; web fetching uses httpx.AsyncClient.
"""
import asyncio
import os
import re
import logging
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup
from bson import ObjectId
from datetime import datetime

from advandeb_kb.models.knowledge import Document, Fact
from advandeb_kb.services.agent_service import AgentService

logger = logging.getLogger(__name__)


def _extract_pdf_text_sync(file_path: str) -> str:
    """Read and extract text from a PDF — runs in a thread pool."""
    import PyPDF2
    text = ""
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text += page.extract_text() or ""
    return text


class DataProcessingService:
    def __init__(self, database):
        self.db = database
        self.documents_collection = database.documents
        self.facts_collection = database.facts
        self.agent_service = AgentService(database)

    # ------------------------------------------------------------------
    # PDF processing
    # ------------------------------------------------------------------

    async def process_pdf(
        self,
        file_path: str,
        filename: str,
        general_domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract text and facts from a local PDF file."""
        try:
            text_content = await asyncio.to_thread(_extract_pdf_text_sync, file_path)

            file_size = await asyncio.to_thread(os.path.getsize, file_path)
            document = Document(
                title=filename,
                source_type="pdf_local",
                source_path=filename,
                content=text_content,
                general_domain=general_domain,
                processing_status="processing",
            )
            doc_data = document.model_dump(by_alias=True)
            await self.documents_collection.insert_one(doc_data)
            document_id = document.id

            facts = await self.agent_service.extract_facts(text_content)

            fact_ids: List[ObjectId] = []
            for fact_text in facts:
                fact = Fact(
                    content=fact_text,
                    document_id=document_id,
                    general_domain=general_domain,
                    confidence=0.8,
                    tags=["pdf", "extracted"],
                )
                fact_data = fact.model_dump(by_alias=True)
                await self.facts_collection.insert_one(fact_data)
                fact_ids.append(fact.id)

            await self.documents_collection.update_one(
                {"_id": document_id},
                {
                    "$set": {
                        "processing_status": "completed",
                        "updated_at": datetime.utcnow(),
                    }
                },
            )

            # Clean up uploaded temp file
            await asyncio.to_thread(os.remove, file_path)

            return {
                "document_id": str(document_id),
                "facts_extracted": len(fact_ids),
                "status": "completed",
            }

        except Exception as e:
            logger.error(f"PDF processing error: {e}")
            if "document_id" in locals():
                await self.documents_collection.update_one(
                    {"_id": document_id},
                    {"$set": {"processing_status": "failed", "updated_at": datetime.utcnow()}},
                )
            raise

    # ------------------------------------------------------------------
    # Web page processing
    # ------------------------------------------------------------------

    async def browse_url(
        self,
        url: str,
        extract_facts: bool = True,
        general_domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch a web page, extract text, and optionally extract facts."""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        }
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()

        raw_text = soup.get_text(separator=" ")
        lines = (line.strip() for line in raw_text.splitlines())
        text_content = " ".join(chunk for line in lines for chunk in line.split("  ") if chunk)
        text_content = text_content[:10_000]

        title = soup.title.string.strip() if soup.title else url

        document = Document(
            title=title,
            source_type="web",
            source_path=url,
            content=text_content,
            general_domain=general_domain,
            processing_status="completed",
        )
        doc_data = document.model_dump(by_alias=True)
        await self.documents_collection.insert_one(doc_data)

        result: Dict[str, Any] = {
            "document_id": str(document.id),
            "url": url,
            "title": title,
            "word_count": len(text_content.split()),
        }

        if extract_facts:
            facts = await self.agent_service.extract_facts(text_content)
            fact_ids: List[str] = []
            for fact_text in facts:
                fact = Fact(
                    content=fact_text,
                    document_id=document.id,
                    general_domain=general_domain,
                    confidence=0.7,
                    tags=["web", "extracted"],
                )
                fact_data = fact.model_dump(by_alias=True)
                await self.facts_collection.insert_one(fact_data)
                fact_ids.append(str(fact.id))
            result["facts_extracted"] = len(fact_ids)
            result["fact_ids"] = fact_ids

        return result

    # ------------------------------------------------------------------
    # Raw text processing
    # ------------------------------------------------------------------

    async def process_text(
        self,
        text: str,
        title: Optional[str] = None,
        extract_facts: bool = True,
        general_domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Store raw text as a document and optionally extract facts."""
        document = Document(
            title=title or "Manual text entry",
            source_type="text",
            content=text,
            general_domain=general_domain,
            processing_status="processing",
        )
        doc_data = document.model_dump(by_alias=True)
        await self.documents_collection.insert_one(doc_data)

        result: Dict[str, Any] = {
            "document_id": str(document.id),
            "word_count": len(text.split()),
            "character_count": len(text),
        }

        if extract_facts:
            facts = await self.agent_service.extract_facts(text)
            fact_ids: List[str] = []
            for fact_text in facts:
                fact = Fact(
                    content=fact_text,
                    document_id=document.id,
                    general_domain=general_domain,
                    confidence=0.8,
                    tags=["text", "extracted"],
                )
                fact_data = fact.model_dump(by_alias=True)
                await self.facts_collection.insert_one(fact_data)
                fact_ids.append(str(fact.id))
            result["facts_extracted"] = len(fact_ids)
            result["fact_ids"] = fact_ids

        await self.documents_collection.update_one(
            {"_id": document.id},
            {"$set": {"processing_status": "completed", "updated_at": datetime.utcnow()}},
        )
        return result

    # ------------------------------------------------------------------
    # Entity extraction (lightweight, no LLM)
    # ------------------------------------------------------------------

    async def extract_entities(self, text: str) -> List[Dict[str, Any]]:
        """Extract biological entity mentions via regex heuristics."""
        patterns = [
            (r"\b[A-Z][a-z]+ [a-z]+\b", "SPECIES"),
            (r"\b\w*protein\b", "MOLECULE"),
            (r"\b\w*enzyme\b", "MOLECULE"),
            (r"\b\w*gene\b", "GENE"),
        ]
        seen: set = set()
        entities: List[Dict[str, Any]] = []
        for pattern, entity_type in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                label = match.group().strip()
                if len(label) > 2 and label.lower() not in seen:
                    seen.add(label.lower())
                    entities.append({
                        "text": label,
                        "start": match.start(),
                        "end": match.end(),
                        "type": entity_type,
                    })
        return entities[:30]

    # ------------------------------------------------------------------
    # Document listing
    # ------------------------------------------------------------------

    async def list_documents(self, skip: int = 0, limit: int = 20) -> List[Dict[str, Any]]:
        cursor = self.documents_collection.find().sort("created_at", -1).skip(skip).limit(limit)
        results = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    async def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        doc = await self.documents_collection.find_one({"_id": ObjectId(document_id)})
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc
