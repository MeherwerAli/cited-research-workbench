from decimal import Decimal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WORKBENCH_", env_file=".env", extra="ignore")

    qdrant_url: str | None = None
    reranker_url: str | None = None
    gateway_url: str | None = None
    gateway_api_key: str | None = None
    approval_threshold_usd: Decimal = Decimal("0.10")
    approval_ttl_seconds: int = Field(default=900, ge=1, le=86_400)
    database_path: str = "data/workbench.db"
    max_pdf_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    max_pdf_pages: int = Field(default=200, ge=1)
