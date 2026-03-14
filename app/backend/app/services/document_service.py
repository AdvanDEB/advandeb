"""
Document service - business logic for document management.
"""
import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from bson import ObjectId
from fastapi import UploadFile

from app.core.database import get_database
from app.models.document import Document, DocumentCreate

logger = logging.getLogger(__name__)


class DocumentService:
    """Service for document operations."""

    def __init__(self):
        self.db = get_database()
        self.collection = self.db.documents

    async def create_document(
        self,
        document: DocumentCreate,
        uploader_id: str,
    ) -> Document:
        """Create a new document."""
        doc_data = document.model_dump()
        doc_data.update({
            "uploader_id": uploader_id,
            "status": "pending",
            "extracted_facts_count": 0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })

        result = await self.collection.insert_one(doc_data)
        doc_data["_id"] = str(result.inserted_id)
        return Document(**doc_data)

    async def upload_document(
        self,
        file: UploadFile,
        uploader_id: str,
    ) -> Document:
        """Upload and create document from file. Extracts text from PDF automatically."""
        content = await file.read()
        filename = file.filename or ""
        content_type = file.content_type or ""

        text_content: Optional[str] = None

        if filename.lower().endswith(".pdf") or "pdf" in content_type:
            try:
                import io
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(content))
                pages_text = []
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pages_text.append(page_text)
                text_content = "\n\n".join(pages_text) if pages_text else None
            except Exception as e:
                logger.warning("PDF text extraction failed for %s: %s", filename, e)
        else:
            try:
                text_content = content.decode("utf-8")
            except Exception:
                text_content = None

        doc_data = {
            "title": filename,
            "source_type": "upload",
            "content": text_content,
            "metadata": {
                "filename": filename,
                "content_type": content_type,
                "size": len(content),
            },
            "uploader_id": uploader_id,
            "status": "pending",
            "extracted_facts_count": 0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

        result = await self.collection.insert_one(doc_data)
        doc_data["_id"] = str(result.inserted_id)
        return Document(**doc_data)

    async def get_document(self, document_id: str) -> Optional[Document]:
        """Get document by ID."""
        doc = await self.collection.find_one({"_id": ObjectId(document_id)})
        if doc:
            doc["_id"] = str(doc["_id"])
            return Document(**doc)
        return None

    async def list_documents(
        self,
        skip: int = 0,
        limit: int = 100,
        search: str = "",
        status: str = "",
    ) -> List[Document]:
        """List documents with optional title search and status filter."""
        query: dict = {}
        if search:
            query["title"] = {"$regex": search, "$options": "i"}
        if status:
            query["status"] = status

        cursor = self.collection.find(query).skip(skip).limit(limit).sort("created_at", -1)
        documents = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            documents.append(Document(**doc))
        return documents

    async def process_document(self, document_id: str) -> dict:
        """Chunk, embed, and store document in ChromaDB."""
        doc = await self.collection.find_one({"_id": ObjectId(document_id)})
        if not doc:
            return {"status": "error", "message": "Document not found"}

        text_content = doc.get("content")
        if not text_content:
            await self.collection.update_one(
                {"_id": ObjectId(document_id)},
                {"$set": {"status": "failed", "updated_at": datetime.utcnow()}},
            )
            return {"status": "failed", "message": "Document has no text content to embed"}

        await self.collection.update_one(
            {"_id": ObjectId(document_id)},
            {"$set": {"status": "processing", "updated_at": datetime.utcnow()}},
        )

        loop = asyncio.get_event_loop()
        try:
            chunk_count = await loop.run_in_executor(
                None,
                self._embed_document_sync,
                document_id,
                text_content,
                doc.get("title", ""),
            )
        except Exception as e:
            logger.error("Embedding pipeline failed for document %s: %s", document_id, e)
            await self.collection.update_one(
                {"_id": ObjectId(document_id)},
                {"$set": {"status": "failed", "updated_at": datetime.utcnow()}},
            )
            return {"status": "failed", "message": str(e)}

        await self.collection.update_one(
            {"_id": ObjectId(document_id)},
            {
                "$set": {
                    "status": "completed",
                    "updated_at": datetime.utcnow(),
                    "extracted_facts_count": chunk_count,
                }
            },
        )
        return {"status": "completed", "chunks_embedded": chunk_count}

    def _embed_document_sync(self, document_id: str, text: str, title: str) -> int:
        """Synchronous embedding pipeline — chunk → embed → store in ChromaDB.
        Runs in a thread-pool executor so it doesn't block the event loop."""
        from advandeb_kb.services.chunking_service import ChunkingService
        from advandeb_kb.services.embedding_service import EmbeddingService
        from advandeb_kb.services.chromadb_service import ChromaDBService

        chunker = ChunkingService()
        embedder = EmbeddingService()
        chroma = ChromaDBService()

        chunks = chunker.chunk_document(text, document_id)
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        embeddings = embedder.embed_batch(texts)

        chunk_ids = [c.chunk_id for c in chunks]
        metadatas = [
            {**c.to_chromadb_metadata(), "title": title}
            for c in chunks
        ]

        chroma.add_chunks_batch(chunk_ids, texts, embeddings, metadatas)
        logger.info("Embedded %d chunks for document %s", len(chunks), document_id)
        return len(chunks)

    async def delete_document(self, document_id: str, user_id: str) -> None:
        """Delete document and its ChromaDB embeddings."""
        try:
            from advandeb_kb.services.chromadb_service import ChromaDBService
            loop = asyncio.get_event_loop()
            chroma = ChromaDBService()
            await loop.run_in_executor(
                None, chroma.delete_chunks_by_document, document_id
            )
        except Exception as e:
            logger.warning(
                "Failed to delete ChromaDB chunks for document %s: %s", document_id, e
            )

        await self.collection.delete_one({"_id": ObjectId(document_id)})
