"""
Document service - business logic for document management.
"""
from datetime import datetime
from typing import List, Optional
from bson import ObjectId
from fastapi import UploadFile

from app.core.database import get_database
from app.models.document import Document, DocumentCreate


class DocumentService:
    """Service for document operations."""
    
    def __init__(self):
        self.db = get_database()
        self.collection = self.db.documents
    
    async def create_document(
        self,
        document: DocumentCreate,
        uploader_id: str
    ) -> Document:
        """Create a new document."""
        doc_data = document.model_dump()
        doc_data.update({
            "uploader_id": uploader_id,
            "status": "pending",
            "extracted_facts_count": 0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        })
        
        result = await self.collection.insert_one(doc_data)
        doc_data["_id"] = str(result.inserted_id)
        return Document(**doc_data)
    
    async def upload_document(
        self,
        file: UploadFile,
        uploader_id: str
    ) -> Document:
        """Upload and create document from file."""
        # Read file content
        content = await file.read()
        
        # TODO: Handle different file types (PDF, DOCX, etc.)
        # For now, assume text content
        try:
            text_content = content.decode('utf-8')
        except:
            text_content = None
        
        doc_data = {
            "title": file.filename,
            "source_type": "upload",
            "content": text_content,
            "metadata": {
                "filename": file.filename,
                "content_type": file.content_type,
                "size": len(content)
            },
            "uploader_id": uploader_id,
            "status": "pending",
            "extracted_facts_count": 0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
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
        """Process document for fact extraction."""
        # TODO: Integrate with advandeb-knowledge-builder
        # from advandeb_kb.ingestion import ingest_document
        # from advandeb_kb.extraction import extract_facts
        
        await self.collection.update_one(
            {"_id": ObjectId(document_id)},
            {"$set": {"status": "processing", "updated_at": datetime.utcnow()}}
        )
        
        # Placeholder - implement actual processing
        return {
            "status": "processing",
            "message": "Document processing started"
        }
    
    async def delete_document(self, document_id: str, user_id: str):
        """Delete document."""
        # TODO: Check ownership or admin role
        await self.collection.delete_one({"_id": ObjectId(document_id)})
