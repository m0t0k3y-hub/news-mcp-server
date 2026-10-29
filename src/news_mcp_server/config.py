"""Runtime configuration loaded from environment variables (or a local .env file)."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    news_api_key: SecretStr
    auth_token: SecretStr
    host: str = "0.0.0.0"
    port: int = 8000
