import hmac

from fastapi import Header, HTTPException
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    optimizer_token: str = Field(min_length=48, repr=False)

    @field_validator("optimizer_token")
    @classmethod
    def random_key(cls, value: str) -> str:
        if len(set(value)) < 16:
            raise ValueError("OPTIMIZER_TOKEN должен быть случайным секретом")
        return value


settings = Settings()


async def require_service_token(x_optimizer_token: str | None = Header(default=None)):
    if not x_optimizer_token or not hmac.compare_digest(x_optimizer_token.encode(), settings.optimizer_token.encode()):
        raise HTTPException(401, "Необходима сервисная авторизация")
