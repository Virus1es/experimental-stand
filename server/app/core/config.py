from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "CacheLab API"
    app_version: str = "0.1.0"

    redis_url: str = "redis://localhost:6379"

    database_url: str = (
        "postgresql+asyncpg://"
        "cachelab:cachelab@localhost:5432/cachelab"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
settings = Settings()