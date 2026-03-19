from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=SERVER_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # SQLite
    sqlite_url: str = f"sqlite:///{SERVER_DIR}/heaven.db"

    # ChromaDB
    chroma_persist_dir: str = str(SERVER_DIR / "chroma_data")
    embedding_model: str = "all-MiniLM-L6-v2"  # swap when model layer is decided

    # LLM provider selection — controls what registry.primary / registry.cheap resolve to.
    # Supported values: "claude" | "openai_compatible"
    # "openai_compatible" covers DeepSeek, OpenRouter, Gemini (via OpenAI endpoint), etc.
    primary_provider: str = "openai_compatible"
    # Default to Perplexity Sonar via OpenRouter; override via env if desired.
    # Use perplexity/sonar (OpenRouter id); sonar-small-chat is deprecated/unavailable.
    primary_model: str = "perplexity/sonar"
    cheap_provider: str = "openai_compatible"
    cheap_model: str = "perplexity/sonar"

    # Anthropic (used when provider = "claude")
    anthropic_api_key: str = ""

    # OpenAI-compatible (used when provider = "openai_compatible")
    # Override openai_base_url for DeepSeek, OpenRouter, Gemini, etc.:
    #   DeepSeek:   https://api.deepseek.com/v1
    #   OpenRouter: https://openrouter.ai/api/v1
    #   Gemini:     https://generativelanguage.googleapis.com/v1beta/openai
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # External APIs
    wolfram_app_id: str = ""
    exa_api_key: str = ""

    # Perplexity web-grounded reasoning fallback
    perplexity_api_key: str = ""
    perplexity_model: str = "sonar"

    # Lean 4
    lean_executable: str = "lean"       # must be on PATH
    lean_project_dir: str = str(SERVER_DIR / "lean_project")
    lean_timeout_seconds: int = 60

    # Rate limiting
    rate_limit: str = "30/minute"

    # CORS — comma-separated allowed origins (use * for development only)
    cors_origins: str = "*"


settings = Settings()
