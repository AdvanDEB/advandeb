from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from typing import List, Dict, Any
from advandeb_kb.services.data_processing_service import DataProcessingService
from advandeb_kb.database.mongodb import get_database
import aiofiles
import os

router = APIRouter()

async def get_data_processing_service():
    db = await get_database()
    return DataProcessingService(db)

@router.post("/upload-pdf")
async def upload_pdf(
    file: UploadFile = File(...),
    service: DataProcessingService = Depends(get_data_processing_service)
):
    """Upload and process PDF file"""
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    
    try:
        # Save uploaded file
        upload_dir = "uploads"
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, file.filename)
        
        async with aiofiles.open(file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)
        
        # Process PDF
        result = await service.process_pdf(file_path, file.filename)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/browse-url")
async def browse_url(
    url: str,
    extract_facts: bool = True,
    service: DataProcessingService = Depends(get_data_processing_service)
):
    """Browse URL and extract content"""
    try:
        result = await service.browse_url(url, extract_facts)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/extract-entities")
async def extract_entities(
    text: str,
    service: DataProcessingService = Depends(get_data_processing_service)
):
    """Extract named entities from text"""
    try:
        entities = await service.extract_entities(text)
        return {"entities": entities}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/process-text")
async def process_text(
    text: str,
    extract_facts: bool = True,
    extract_entities: bool = True,
    service: DataProcessingService = Depends(get_data_processing_service)
):
    """Process raw text and extract facts and entities"""
    try:
        result = await service.process_text(text, extract_facts, extract_entities)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/documents")
async def list_documents(
    skip: int = 0,
    limit: int = 10,
    service: DataProcessingService = Depends(get_data_processing_service)
):
    """List processed documents"""
    try:
        documents = await service.list_documents(skip, limit)
        return {"documents": documents}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    service: DataProcessingService = Depends(get_data_processing_service)
):
    """Get document details"""
    try:
        document = await service.get_document(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        return document
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))