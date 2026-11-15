"""Central settings. Every other file does:  from app.config import settings"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Gemini ---
    google_api_key: str
    gemini_chat_model: str = "gemini-2.5-flash"
    gemini_embedding_model: str = "gemini-embedding-001"

    # --- Vector store / retrieval ---
    chroma_dir: str = "./chroma_db"
    retrieval_k: int = 3

    # --- FreshGuard ---
    use_mock_freshguard: bool = True
    freshguard_base_url: str = "http://localhost:8000"
    freshguard_api_key: str = "dev-key"
    # Seconds per request. A free Render server sleeps when idle and can take 30-60 s to wake.
    freshguard_timeout: float = 60.0
    mock_delay_seconds: float = 6.0

    # --- Web ---
    cors_origins: str = "http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
