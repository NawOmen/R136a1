from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://sborka:sborka@localhost:5433/sborka"
    jwt_secret: str = "dev-secret-change-me-0123456789abcdef"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440


settings = Settings()
