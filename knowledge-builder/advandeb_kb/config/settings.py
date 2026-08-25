"""
Knowledge-builder settings.

All values can be overridden via environment variables.  The recommended
approach is a .env file in the repo root or the knowledge-builder/ directory,
loaded by python-dotenv before this module is imported.
"""
import os
from typing import Optional


class Settings:
    # ------------------------------------------------------------------
    # MongoDB — used for ingestion workflow state only
    # (ingestion_batches, ingestion_jobs collections).
    # All KB knowledge data (documents, facts, taxa, etc.) lives in ArangoDB.
    # ------------------------------------------------------------------
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "advandeb_knowledge_builder_kb")
    CHAT_STORE_DB_NAME: str = os.getenv("CHAT_STORE_DB_NAME", "advandeb")

    # ------------------------------------------------------------------
    # ArangoDB — primary KB data store (documents, facts, stylized_facts,
    # taxonomy, chunks/embeddings, graphs, provenance).
    # ------------------------------------------------------------------
    ARANGO_URL: str = os.getenv("ARANGO_URL", "http://localhost:8529")
    ARANGO_DB_NAME: str = os.getenv("ARANGO_DB_NAME", "advandeb_kb")
    ARANGO_USERNAME: str = os.getenv("ARANGO_USERNAME", "root")
    ARANGO_PASSWORD: str = os.getenv("ARANGO_PASSWORD", "")

    # ------------------------------------------------------------------
    # Ollama (sole LLM provider)
    # ------------------------------------------------------------------
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "deepseek-r1:latest")
    # Context window: 16384 tokens is sufficient for the ReAct loop.
    # deepseek-r1:latest (8B) is ~6x faster than 70B and fits one GPU.
    OLLAMA_NUM_CTX: int = int(os.getenv("OLLAMA_NUM_CTX", "16384"))

    # Chat role-specific settings.
    CHAT_MODE: str = os.getenv("CHAT_MODE", "react")
    CHAT_DEFAULT_TOP_K: int = int(os.getenv("CHAT_DEFAULT_TOP_K", "20"))
    CHAT_ENABLE_EXTERNAL_FALLBACK: bool = (
        os.getenv("CHAT_ENABLE_EXTERNAL_FALLBACK", "true").lower() == "true"
    )
    CHAT_ANSWER_MODEL: str = os.getenv("CHAT_ANSWER_MODEL", OLLAMA_MODEL)
    CHAT_VERIFY_MODEL: str = os.getenv("CHAT_VERIFY_MODEL", "deepseek-r1:latest")
    CHAT_GRAPH_MODEL: str = os.getenv("CHAT_GRAPH_MODEL", "gemma3:latest")
    CHAT_FOLLOWUP_MODEL: str = os.getenv("CHAT_FOLLOWUP_MODEL", "gemma3:latest")
    CHAT_EXTERNAL_FALLBACK_MODEL: str = os.getenv(
        "CHAT_EXTERNAL_FALLBACK_MODEL",
        CHAT_ANSWER_MODEL,
    )
    CHAT_ANSWER_NUM_CTX: int = int(os.getenv("CHAT_ANSWER_NUM_CTX", str(OLLAMA_NUM_CTX)))
    # Max output tokens for the final answer (both Ollama num_predict and BYOK
    # provider max_tokens). 1200 was too small and truncated answers — and for
    # reasoning models the <think> block also consumes this budget.
    CHAT_ANSWER_MAX_TOKENS: int = int(os.getenv("CHAT_ANSWER_MAX_TOKENS", "32000"))
    CHAT_VERIFY_NUM_CTX: int = int(os.getenv("CHAT_VERIFY_NUM_CTX", "4096"))
    CHAT_GRAPH_NUM_CTX: int = int(os.getenv("CHAT_GRAPH_NUM_CTX", "4096"))
    CHAT_FOLLOWUP_NUM_CTX: int = int(os.getenv("CHAT_FOLLOWUP_NUM_CTX", "2048"))
    CHAT_EXTERNAL_NUM_CTX: int = int(os.getenv("CHAT_EXTERNAL_NUM_CTX", str(OLLAMA_NUM_CTX)))

    # ------------------------------------------------------------------
    # Exploration quality (ReAct retrieval + reasoning)
    # ------------------------------------------------------------------
    # Max ReAct tool-calling steps before forcing a final answer.
    CHAT_MAX_STEPS: int = int(os.getenv("CHAT_MAX_STEPS", "15"))
    # Rerank fused hybrid-search candidates with the LLM reranker for precision.
    CHAT_USE_RERANKING: bool = os.getenv("CHAT_USE_RERANKING", "true").lower() == "true"
    # Enable adaptive thinking / reasoning-effort on any BYOK provider that
    # supports it (Anthropic adaptive thinking, OpenAI/GitHub reasoning_effort,
    # Gemini thinking, Ollama think). No-ops gracefully where unsupported.
    CHAT_ADAPTIVE_THINKING: bool = (
        os.getenv("CHAT_ADAPTIVE_THINKING", "true").lower() == "true"
    )
    # Effort level when adaptive thinking is on: low | medium | high | max.
    CHAT_THINKING_EFFORT: str = os.getenv("CHAT_THINKING_EFFORT", "high")

    # ------------------------------------------------------------------
    # API / service
    # ------------------------------------------------------------------
    API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
    API_PORT: int = int(os.getenv("API_PORT", "8000"))
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", "50000000"))  # 50 MB
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")

    # ------------------------------------------------------------------
    # Background processing
    # ------------------------------------------------------------------
    # Empty string = Redis disabled; CacheService falls back to in-process LRU.
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    PAPERS_ROOT: str = os.getenv("PAPERS_ROOT", "/home/adeb/DEB_library")

    # 0 = auto-estimate based on available VRAM/RAM/CPU at startup.
    INGESTION_CONCURRENCY: int = int(os.getenv("INGESTION_CONCURRENCY", "0"))

    # ------------------------------------------------------------------
    # OpenAlex
    # ------------------------------------------------------------------
    OPENALEX_EMAIL: str = os.getenv("OPENALEX_EMAIL", "domagojhack@gmail.com")

    # ------------------------------------------------------------------
    # ChromaDB — being replaced by ArangoDB vector index (v3.12+).
    # Still used during migration; will be removed in Step 5.
    # ------------------------------------------------------------------
    CHROMA_PERSIST_DIR: str = os.getenv(
        "CHROMA_PERSIST_DIR", "/home/adeb/dev/advandeb/data/chromadb"
    )
    CHROMA_COLLECTION: str = os.getenv("CHROMA_COLLECTION", "advandeb_chunks")

    # ------------------------------------------------------------------
    # Embedding model
    # ------------------------------------------------------------------
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")


settings = Settings()
