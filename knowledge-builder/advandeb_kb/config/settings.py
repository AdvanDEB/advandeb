"""
Knowledge-builder settings.

Every value resolves environment → env file → default, exactly as the web
app's settings do (see ``advandeb_kb.config.env``), so the app, the agents
and the scripts read one ``app/backend/.env`` under one set of names.
"""
from pathlib import Path

from advandeb_kb.config.env import REPO_ROOT, getenv, getenv_bool, getenv_int


class Settings:
    # ------------------------------------------------------------------
    # MongoDB — used for ingestion workflow state only
    # (ingestion_batches, ingestion_jobs collections).
    # All KB knowledge data (documents, facts, taxa, etc.) lives in ArangoDB.
    #
    # Canonical names are the app's (MONGODB_URI, KB_DB_NAME). The KB's old
    # spellings MONGODB_URL / DATABASE_NAME are still honoured as aliases and
    # still exposed as attributes, but new code should use the canonical ones.
    # ------------------------------------------------------------------
    MONGODB_URI: str = getenv("MONGODB_URI", "mongodb://localhost:27017", aliases=("MONGODB_URL",))
    KB_DB_NAME: str = getenv("KB_DB_NAME", "advandeb_knowledge_builder_kb", aliases=("DATABASE_NAME",))
    MONGODB_URL: str = MONGODB_URI      # deprecated alias
    DATABASE_NAME: str = KB_DB_NAME     # deprecated alias
    # The app database (users, chat). Same value the app calls MONGODB_DB_NAME.
    CHAT_STORE_DB_NAME: str = getenv("CHAT_STORE_DB_NAME", "advandeb", aliases=("MONGODB_DB_NAME",))

    # ------------------------------------------------------------------
    # ArangoDB — primary KB data store (documents, facts, stylized_facts,
    # taxonomy, chunks/embeddings, graphs, provenance).
    # ------------------------------------------------------------------
    ARANGO_URL: str = getenv("ARANGO_URL", "http://localhost:8529")
    ARANGO_DB_NAME: str = getenv("ARANGO_DB_NAME", "advandeb_kb")
    ARANGO_USERNAME: str = getenv("ARANGO_USERNAME", "root")
    ARANGO_PASSWORD: str = getenv("ARANGO_PASSWORD", "")

    # ------------------------------------------------------------------
    # Ollama (sole LLM provider)
    # ------------------------------------------------------------------
    OLLAMA_BASE_URL: str = getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = getenv("OLLAMA_MODEL", "deepseek-r1:latest")
    # Context window: 16384 tokens is sufficient for the ReAct loop.
    # deepseek-r1:latest (8B) is ~6x faster than 70B and fits one GPU.
    OLLAMA_NUM_CTX: int = getenv_int("OLLAMA_NUM_CTX", 16384)

    # Chat role-specific settings.
    CHAT_MODE: str = getenv("CHAT_MODE", "react")
    CHAT_DEFAULT_TOP_K: int = getenv_int("CHAT_DEFAULT_TOP_K", 20)
    CHAT_ENABLE_EXTERNAL_FALLBACK: bool = (
        getenv_bool("CHAT_ENABLE_EXTERNAL_FALLBACK", True)
    )
    CHAT_ANSWER_MODEL: str = getenv("CHAT_ANSWER_MODEL", OLLAMA_MODEL)
    CHAT_VERIFY_MODEL: str = getenv("CHAT_VERIFY_MODEL", "deepseek-r1:latest")
    CHAT_GRAPH_MODEL: str = getenv("CHAT_GRAPH_MODEL", "gemma3:latest")
    CHAT_FOLLOWUP_MODEL: str = getenv("CHAT_FOLLOWUP_MODEL", "gemma3:latest")
    CHAT_EXTERNAL_FALLBACK_MODEL: str = getenv(
        "CHAT_EXTERNAL_FALLBACK_MODEL",
        CHAT_ANSWER_MODEL,
    )
    CHAT_ANSWER_NUM_CTX: int = getenv_int("CHAT_ANSWER_NUM_CTX", OLLAMA_NUM_CTX)
    # Max output tokens for the final answer (both Ollama num_predict and BYOK
    # provider max_tokens). 1200 was too small and truncated answers — and for
    # reasoning models the <think> block also consumes this budget.
    CHAT_ANSWER_MAX_TOKENS: int = getenv_int("CHAT_ANSWER_MAX_TOKENS", 32000)
    CHAT_VERIFY_NUM_CTX: int = getenv_int("CHAT_VERIFY_NUM_CTX", 4096)
    CHAT_GRAPH_NUM_CTX: int = getenv_int("CHAT_GRAPH_NUM_CTX", 4096)
    CHAT_FOLLOWUP_NUM_CTX: int = getenv_int("CHAT_FOLLOWUP_NUM_CTX", 2048)
    CHAT_EXTERNAL_NUM_CTX: int = getenv_int("CHAT_EXTERNAL_NUM_CTX", OLLAMA_NUM_CTX)

    # ------------------------------------------------------------------
    # Exploration quality (ReAct retrieval + reasoning)
    # ------------------------------------------------------------------
    # Max ReAct tool-calling steps before forcing a final answer.
    CHAT_MAX_STEPS: int = getenv_int("CHAT_MAX_STEPS", 15)
    # Rerank fused hybrid-search candidates with the LLM reranker (RERANK_MODEL).
    # Off by default: on the SF-support eval (59 queries) gemma3 reranking moved
    # MRR by +0.023 (95% CI -0.061..+0.108) for +1.3 s per search. Until 2026-10
    # it was nominally on but 404'd on every call (model "llama2" not installed).
    CHAT_USE_RERANKING: bool = getenv_bool("CHAT_USE_RERANKING", False)
    # Enable adaptive thinking / reasoning-effort on any BYOK provider that
    # supports it (Anthropic adaptive thinking, OpenAI/GitHub reasoning_effort,
    # Gemini thinking, Ollama think). No-ops gracefully where unsupported.
    CHAT_ADAPTIVE_THINKING: bool = (
        getenv_bool("CHAT_ADAPTIVE_THINKING", True)
    )
    # Effort level when adaptive thinking is on: low | medium | high | max.
    CHAT_THINKING_EFFORT: str = getenv("CHAT_THINKING_EFFORT", "high")

    # ------------------------------------------------------------------
    # Hybrid retrieval (HybridRetrievalService / RetrievalAgent)
    # ------------------------------------------------------------------
    # Keyword arm: "auto" = BM25 over the ArangoSearch view when it exists,
    # otherwise the MongoDB $text fallback; or force "arango" | "mongo" | "none".
    RETRIEVAL_KEYWORD_BACKEND: str = getenv("RETRIEVAL_KEYWORD_BACKEND", "auto")
    # ArangoSearch view over chunks.text and the analyzer it indexes with
    # (created by knowledge-builder/scripts/setup_chunks_search_view.py).
    RETRIEVAL_CHUNKS_VIEW: str = getenv("RETRIEVAL_CHUNKS_VIEW", "chunks_text_search")
    RETRIEVAL_TEXT_ANALYZER: str = getenv("RETRIEVAL_TEXT_ANALYZER", "advandeb_text_en")
    # ArangoSearch views over facts.content and stylized_facts.statement, same
    # analyzer: BM25 for KnowledgeService.search_facts / search_stylized_facts
    # (created by knowledge-builder/scripts/setup_facts_search_views.py).
    # Until they exist, search falls back to an unranked LIKE scan.
    FACTS_SEARCH_VIEW: str = getenv("FACTS_SEARCH_VIEW", "facts_text_search")
    STYLIZED_FACTS_SEARCH_VIEW: str = getenv("STYLIZED_FACTS_SEARCH_VIEW", "stylized_facts_text_search")
    # Ollama model for the LLM reranker (CHAT_USE_RERANKING). Must be
    # installed; a missing model disables reranking with one warning.
    RERANK_MODEL: str = getenv("RERANK_MODEL", "gemma3:latest")
    RERANK_TIMEOUT: float = float(getenv("RERANK_TIMEOUT", "30"))

    # ------------------------------------------------------------------
    # Fact extraction (app/backend/app/kb/pipeline.py::_extract_facts)
    # ------------------------------------------------------------------
    # Ollama loads a model with a 4096-token context (2048 per slot with
    # OLLAMA_NUM_PARALLEL=2) unless the request sets num_ctx, and silently
    # drops whatever does not fit. Sections are sized to fit this window.
    # Matching OLLAMA_NUM_CTX lets ingestion share the chat's loaded runner
    # instead of forcing a reload.
    FACT_EXTRACTION_NUM_CTX: int = getenv_int("FACT_EXTRACTION_NUM_CTX", OLLAMA_NUM_CTX)
    # Output budget reserved inside the window (JSON facts plus <think>).
    FACT_EXTRACTION_NUM_PREDICT: int = getenv_int("FACT_EXTRACTION_NUM_PREDICT", 4096)

    # ------------------------------------------------------------------
    # API / service
    # ------------------------------------------------------------------
    API_HOST: str = getenv("API_HOST", "0.0.0.0")
    API_PORT: int = getenv_int("API_PORT", 8000)
    MAX_FILE_SIZE: int = getenv_int("MAX_FILE_SIZE", 50000000)  # 50 MB
    UPLOAD_DIR: str = getenv("UPLOAD_DIR", "uploads")

    # ------------------------------------------------------------------
    # Background processing
    # ------------------------------------------------------------------
    # Empty string = Redis disabled; CacheService falls back to in-process LRU.
    REDIS_URL: str = getenv("REDIS_URL", "")
    PAPERS_ROOT: str = getenv("PAPERS_ROOT", str(Path.home() / "DEB_library"))

    # 0 = auto-estimate based on available VRAM/RAM/CPU at startup.
    INGESTION_CONCURRENCY: int = getenv_int("INGESTION_CONCURRENCY", 0)

    # ------------------------------------------------------------------
    # OpenAlex
    # ------------------------------------------------------------------
    OPENALEX_EMAIL: str = getenv("OPENALEX_EMAIL", "domagojhack@gmail.com")

    # ------------------------------------------------------------------
    # ChromaDB — being replaced by ArangoDB vector index (v3.12+).
    # Still used during migration; will be removed in Step 5.
    # ------------------------------------------------------------------
    CHROMA_PERSIST_DIR: str = getenv("CHROMA_PERSIST_DIR", str(REPO_ROOT / "data" / "chromadb"))
    CHROMA_COLLECTION: str = getenv("CHROMA_COLLECTION", "advandeb_chunks")

    # ------------------------------------------------------------------
    # Embedding model
    # ------------------------------------------------------------------
    EMBEDDING_MODEL: str = getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")


settings = Settings()
