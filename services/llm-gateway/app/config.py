from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://sborka:sborka@localhost:5433/sborka"
    jwt_secret: str = "dev-secret-change-me-0123456789abcdef"
    jwt_algorithm: str = "HS256"

    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen3.5:9b"
    ollama_timeout_seconds: float = 180.0
    llm_context_tokens: int = 8192

    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-pro"
    deepseek_timeout_seconds: float = 45.0

    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    max_upload_bytes: int = 25 * 1024 * 1024
    max_combined_text_chars: int = 120_000


settings = Settings()
