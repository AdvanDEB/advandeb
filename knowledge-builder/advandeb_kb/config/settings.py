import os
from typing import Optional

class Settings:
    # MongoDB settings
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "advandeb_knowledge_builder_kb")

    # Ollama settings (sole LLM provider)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # API settings
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))

    # File upload settings
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", "50000000"))  # 50MB
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")

    # Ingestion and background processing settings
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    PAPERS_ROOT: str = os.getenv("PAPERS_ROOT", "../papers")

settings = Settings()
