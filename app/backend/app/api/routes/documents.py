"""
Document management API routes.
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from typing import List

from app.core.auth import get_current_user
from app.core.dependencies import require_curator
from app.models.document import Document, DocumentCreate
from app.services.document_service import DocumentService


router = APIRouter()


@router.post("/", response_model=Document)
async def create_document(
    document: DocumentCreate,
    current_user: dict = Depends(require_curator)
):
    """Create a new document."""
    doc_service = DocumentService()
    new_doc = await doc_service.create_document(document, current_user["id"])
    return new_doc


@router.post("/upload", response_model=Document)
async def upload_document(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_curator)
):
    """Upload a document file."""
    doc_service = DocumentService()
    document = await doc_service.upload_document(file, current_user["id"])
    return document


@router.get("/", response_model=List[Document])
async def list_documents(
    skip: int = 0,
    limit: int = 100,
    search: str = "",
    status: str = "",
    current_user: dict = Depends(get_current_user)
):
    """List documents with optional search and status filter."""
    doc_service = DocumentService()
    documents = await doc_service.list_documents(skip=skip, limit=limit, search=search, status=status)
    return documents


@router.get("/{document_id}", response_model=Document)
async def get_document(
    document_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get document by ID."""
    doc_service = DocumentService()
    document = await doc_service.get_document(document_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found"
        )
    return document


@router.post("/{document_id}/process")
async def process_document(
    document_id: str,
    current_user: dict = Depends(require_curator)
):
    """Process document for fact extraction."""
    doc_service = DocumentService()
    result = await doc_service.process_document(document_id)
    return result


@router.post("/{document_id}/embed")
async def embed_document(
    document_id: str,
    current_user: dict = Depends(require_curator)
):
    """Trigger embedding / vector indexing for a document."""
    doc_service = DocumentService()
    result = await doc_service.process_document(document_id)
    return result


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    current_user: dict = Depends(require_curator)
):
    """Delete document."""
    doc_service = DocumentService()
    await doc_service.delete_document(document_id, current_user["id"])
    return {"message": "Document deleted"}
