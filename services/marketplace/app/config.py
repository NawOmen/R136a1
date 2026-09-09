from typing import Literal
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

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = Field(min_length=16, repr=False)
    minio_bucket: str = "sborka"
    optimizer_url: str = "http://optimizer:8004"
    optimizer_token: str = Field(repr=False, min_length=48)

    @field_validator("optimizer_token")
    @classmethod
    def random_optimizer_key(cls, value: str) -> str:
        if len(set(value)) < 16:
            raise ValueError("OPTIMIZER_TOKEN должен быть случайным секретом")
        return value
    optimizer_timeout_seconds: float = 15.0
    minio_secure: bool = False
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cors_origin_regex: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
