import os
from typing import Optional

class Settings:
    # MongoDB settings
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "advandeb_knowledge_builder_kb")

    # Ollama settings (sole LLM provider)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "deepseek-r1:latest")

    # API settings
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    # File upload settings
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", "50000000"))  # 50MB
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")

    # Ingestion and background processing settings
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    PAPERS_ROOT: str = os.getenv("PAPERS_ROOT", "/home/adeb/DEB_library")

    # Maximum number of PDFs to ingest in parallel.
    # Set to 0 (default) to let the pipeline auto-estimate based on available
    # VRAM, RAM, and CPU count at startup.  Set to a positive integer to pin
    # the value regardless of hardware (e.g. INGESTION_CONCURRENCY=4).
    INGESTION_CONCURRENCY: int = int(os.getenv("INGESTION_CONCURRENCY", "0"))

    # ChromaDB settings (vector store — embedded/in-process mode by default)
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./data/chromadb")
    CHROMA_COLLECTION: str = os.getenv("CHROMA_COLLECTION", "advandeb_chunks")

    # Embedding model (sentence-transformers)
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

settings = Settings()
