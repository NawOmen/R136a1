from typing import Literal
from decimal import Decimal
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: str = "postgresql+asyncpg://sborka:sborka@localhost:5433/sborka"
    jwt_secret: str = Field(repr=False)

    @field_validator("jwt_secret")
    @classmethod
    def strong_signing_key(cls, value: str) -> str:
        if len(value) < 48 or len(set(value)) < 16 or value.startswith("dev-secret"):
            raise ValueError("JWT_SECRET должен быть случайным секретом длиной не менее 48 символов")
        return value

    jwt_algorithm: Literal["HS256"] = "HS256"

    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "qwen3.5:9b"
    ollama_timeout_seconds: float = 180.0
    llm_context_tokens: int = 8192
    local_inference_cost_rub_per_minute: Decimal = Field(default=Decimal("0.35"),ge=0,le=Decimal("999999999999.999999999999"),max_digits=24,decimal_places=12,allow_inf_nan=False)

    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-pro"
    deepseek_timeout_seconds: float = 45.0

    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    max_upload_bytes: int = 25 * 1024 * 1024
    max_combined_text_chars: int = 120_000
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cors_origin_regex: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
