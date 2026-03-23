from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    S3_ENDPOINT: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "admin"
    S3_SECRET_KEY: str = "password123"
    S3_BUCKET: str = "images"

    @field_validator("S3_ENDPOINT")
    @classmethod
    def validate_endpoint(cls, v: str):
        if not v.startswith("http"):
            raise ValueError("S3_ENDPOINT должен начинаться с http/https")
        return v

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()