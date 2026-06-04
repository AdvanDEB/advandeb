"""
Application configuration settings.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List, Optional


class Settings(BaseSettings):
    """Application settings."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        env_file_encoding='utf-8'
    )
    
    # Application
    APP_NAME: str = "AdvanDEB Modeling Assistant"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Security
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    
    # Google OAuth (optional — native login works without these)
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[str] = None

    @property
    def google_oauth_enabled(self) -> bool:
        """True when all three Google OAuth credentials are configured."""
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET and self.GOOGLE_REDIRECT_URI)

    # GitHub OAuth device flow (BYOK "Connect with GitHub" → GitHub Models).
    # Register your own GitHub App with Device Flow enabled + `Models: read`
    # permission, and put its client ID here. No client secret is needed for the
    # device flow. Leave unset to hide the feature. GITHUB_OAUTH_SCOPE is only
    # used by classic OAuth Apps (GitHub Apps derive access from their granted
    # permissions and ignore it).
    GITHUB_OAUTH_CLIENT_ID: Optional[str] = None
    GITHUB_OAUTH_SCOPE: Optional[str] = None

    @property
    def github_oauth_enabled(self) -> bool:
        """True when a GitHub OAuth client id is configured."""
        return bool(self.GITHUB_OAUTH_CLIENT_ID)
    
    # MongoDB — app layer (users, auth, chat, user submissions)
    MONGODB_URI: str
    MONGODB_DB_NAME: str = "advandeb"
    # Transitional: KB_DB_NAME used during MongoDB→ArangoDB migration. Remove after migration.
    KB_DB_NAME: str = "advandeb_knowledge_builder_kb"

    # ArangoDB — KB primary store
    ARANGO_URL: str = "http://localhost:8529"
    ARANGO_DB_NAME: str = "advandeb_kb"
    ARANGO_USERNAME: str = "root"
    ARANGO_PASSWORD: str = ""
    
    # MCP Server
    MCP_SERVER_URL: str = "http://localhost:8080"
    MCP_SERVER_ENABLED: bool = True

    # Chatbot agent WebSocket endpoint (used by the chat WS bridge in B10)
    CHATBOT_AGENT_WS: str = "ws://localhost:8086"

    # Ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    
    # CORS - comma-separated string that will be split into list
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"
    
    # KB ingestion
    PAPERS_ROOT: str = "/home/adeb/DEB_library"

    # Graph artifacts
    GRAPH_ARTIFACT_DIR: str = "data/graph_artifacts"
    GRAPH_ARTIFACT_LAYOUT_NAME: str = "schema_default_v1"

    # MongoDB connection pool
    MONGO_MAX_POOL_SIZE: int = 10

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "logs/app.log"

    # BYOK — Fernet key for encrypting user-supplied LLM API keys at rest.
    # Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Leave unset to disable the BYOK feature; the rest of the app still boots.
    LLM_KEY_ENCRYPTION_KEY: Optional[str] = None
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Convert CORS_ORIGINS string to list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    @field_validator("LLM_KEY_ENCRYPTION_KEY")
    @classmethod
    def _validate_llm_key_encryption_key(cls, value: Optional[str]) -> Optional[str]:
        """Allow None (BYOK disabled). If set, must be a Fernet-accepted 44-char base64 key."""
        if value in (None, ""):
            return None
        # Fernet keys are URL-safe base64-encoded 32-byte values → 44 chars total.
        if len(value) != 44:
            raise ValueError(
                "LLM_KEY_ENCRYPTION_KEY must be a 44-char URL-safe base64 Fernet key "
                "(generate with: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\")"
            )
        try:
            from cryptography.fernet import Fernet
            Fernet(value.encode())
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"LLM_KEY_ENCRYPTION_KEY is not a valid Fernet key: {exc}") from exc
        return value

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def _validate_jwt_secret_key(cls, value: str, info) -> str:
        """Reject empty / weak / example JWT_SECRET_KEY values outside development.

        ENVIRONMENT is declared before JWT_SECRET_KEY, so by Pydantic v2's
        declaration-order validation it is already present in ``info.data``.
        """
        environment = info.data.get("ENVIRONMENT", "development")
        if environment != "development":
            if (
                not value
                or len(value) < 32
                or "your-secret-key-here" in value
            ):
                raise ValueError(
                    "JWT_SECRET_KEY is unset or uses the example value; "
                    f"refusing to start with ENVIRONMENT={environment}"
                )
        return value


settings = Settings()
