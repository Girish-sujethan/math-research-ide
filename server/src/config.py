from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

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

    # External APIs
    wolfram_app_id: str = ""
    semantic_scholar_api_key: str = ""  # optional — raises rate limit without key

    # Lean 4
    lean_executable: str = "lean"       # must be on PATH
    lean_project_dir: str = str(SERVER_DIR / "lean_project")
    lean_timeout_seconds: int = 60


settings = Settings()
