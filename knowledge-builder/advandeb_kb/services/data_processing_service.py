import PyPDF2
import requests
from bs4 import BeautifulSoup
import aiofiles
import os
from typing import List, Dict, Any, Optional
from advandeb_kb.models.knowledge import Document, Fact
from advandeb_kb.services.agent_service import AgentService
from bson import ObjectId
from datetime import datetime
import logging
import re

logger = logging.getLogger(__name__)

class DataProcessingService:
    def __init__(self, database):
        self.db = database
        self.documents_collection = database.documents
        self.facts_collection = database.facts
        self.agent_service = AgentService(database)

    async def process_pdf(self, file_path: str, filename: str) -> Dict[str, Any]:
        """Process PDF file and extract facts"""
        try:
            # Extract text from PDF
            text_content = await self._extract_pdf_text(file_path)
            
            # Create document record
            file_size = os.path.getsize(file_path)
            document = Document(
                filename=filename,
                file_type="pdf",
                file_size=file_size,
                content=text_content,
                processing_status="processing"
            )
            
            # Save document
            doc_dict = document.dict(by_alias=True, exclude_unset=True)
            doc_dict["_id"] = ObjectId()
            result = await self.documents_collection.insert_one(doc_dict)
            document_id = result.inserted_id
            
            # Extract facts using AI
            facts = await self.agent_service.extract_facts(text_content)
            
            # Save facts and link to document
            fact_ids = []
            for fact_text in facts:
                fact = Fact(
                    content=fact_text,
                    source=f"PDF: {filename}",
                    confidence=0.8,
                    tags=["pdf", "extracted"]
                )
                fact_dict = fact.dict(by_alias=True, exclude_unset=True)
                fact_dict["_id"] = ObjectId()
                fact_result = await self.facts_collection.insert_one(fact_dict)
                fact_ids.append(fact_result.inserted_id)
            
            # Update document with extracted facts
            await self.documents_collection.update_one(
                {"_id": document_id},
                {
                    "$set": {
                        "facts_extracted": fact_ids,
                        "processing_status": "completed",
                        "processed_at": datetime.utcnow()
                    }
                }
            )
            
            # Clean up file
            os.remove(file_path)
            
            return {
                "document_id": str(document_id),
                "facts_extracted": len(fact_ids),
                "status": "completed"
            }
            
        except Exception as e:
            logger.error(f"PDF processing error: {e}")
            # Update document status to failed
            if 'document_id' in locals():
                await self.documents_collection.update_one(
                    {"_id": document_id},
                    {"$set": {"processing_status": "failed"}}
                )
            raise

    async def _extract_pdf_text(self, file_path: str) -> str:
        """Extract text from PDF file"""
        text = ""
        with open(file_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                text += page.extract_text()
        return text

    async def browse_url(self, url: str, extract_facts: bool = True) -> Dict[str, Any]:
        """Browse URL and extract content"""
        try:
            # Fetch webpage content
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Parse HTML content
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Extract text
            text_content = soup.get_text()
            
            # Clean up text
            lines = (line.strip() for line in text_content.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text_content = ' '.join(chunk for chunk in chunks if chunk)
            
            # Limit text length
            text_content = text_content[:10000]  # Limit to 10k characters
            
            result = {
                "url": url,
                "title": soup.title.string if soup.title else "No title",
                "content": text_content,
                "word_count": len(text_content.split())
            }
            
            if extract_facts:
                # Extract facts using AI
                facts = await self.agent_service.extract_facts(text_content)
                result["facts"] = facts
                
                # Optionally save facts to database
                fact_ids = []
                for fact_text in facts:
                    fact = Fact(
                        content=fact_text,
                        source=f"Web: {url}",
                        confidence=0.7,
                        tags=["web", "extracted"]
                    )
                    fact_dict = fact.dict(by_alias=True, exclude_unset=True)
                    fact_dict["_id"] = ObjectId()
                    fact_result = await self.facts_collection.insert_one(fact_dict)
                    fact_ids.append(str(fact_result.inserted_id))
                
                result["fact_ids"] = fact_ids
            
            return result
            
        except Exception as e:
            logger.error(f"URL browsing error: {e}")
            raise

    async def extract_entities(self, text: str) -> List[Dict[str, Any]]:
        """Extract named entities from text"""
        # Simple regex-based entity extraction
        # In a production system, you'd use spaCy or similar NLP library
        entities = []
        
        # Extract potential biological terms (simplified)
        biological_patterns = [
            r'\b[A-Z][a-z]+ [a-z]+\b',  # Genus species
            r'\b\w*protein\b',          # Proteins
            r'\b\w*enzyme\b',           # Enzymes
            r'\b\w*gene\b',             # Genes
            r'\b\w*cell\b',             # Cells
            r'\b\w*tissue\b',           # Tissues
            r'\b\w*organ\b',            # Organs
        ]
        
        for pattern in biological_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                entity_text = match.group().strip()
                if len(entity_text) > 2:  # Filter very short matches
                    entities.append({
                        "text": entity_text,
                        "start": match.start(),
                        "end": match.end(),
                        "type": "BIOLOGICAL"
                    })
        
        # Remove duplicates
        unique_entities = []
        seen = set()
        for entity in entities:
            if entity["text"].lower() not in seen:
                unique_entities.append(entity)
                seen.add(entity["text"].lower())
        
        return unique_entities[:20]  # Limit to 20 entities

    async def process_text(self, text: str, extract_facts: bool = True, extract_entities: bool = True) -> Dict[str, Any]:
        """Process raw text and extract facts and entities"""
        result = {
            "text": text,
            "word_count": len(text.split()),
            "character_count": len(text)
        }
        
        if extract_facts:
            facts = await self.agent_service.extract_facts(text)
            result["facts"] = facts
        
        if extract_entities:
            entities = await self.extract_entities(text)
            result["entities"] = entities
        
        return result

    async def list_documents(self, skip: int = 0, limit: int = 10) -> List[Dict[str, Any]]:
        """List processed documents"""
        cursor = self.documents_collection.find().skip(skip).limit(limit).sort("created_at", -1)
        documents = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            doc["facts_extracted"] = [str(fid) for fid in doc.get("facts_extracted", [])]
            documents.append(doc)
        return documents

    async def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Get document details"""
        doc = await self.documents_collection.find_one({"_id": ObjectId(document_id)})
        if doc:
            doc["_id"] = str(doc["_id"])
            doc["facts_extracted"] = [str(fid) for fid in doc.get("facts_extracted", [])]
        return doc