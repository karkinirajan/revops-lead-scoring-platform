from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: Literal["development", "staging", "production"] = "development"
    app_secret_key: str = "insecure-dev-secret-change-me"
    app_debug: bool = False
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+psycopg2://revops:revops_pass@localhost:5432/revops"
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout: int = 30

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_db: int = 1
    redis_lock_ttl_seconds: int = 300

    # Auth / JWT
    jwt_secret_key: str = "insecure-dev-jwt-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 7

    # Admin seed
    admin_email: str = "admin@example.com"
    admin_password: str = "change-me-strong-password"

    # HubSpot
    hubspot_access_token: str = ""
    hubspot_portal_id: str = ""
    hubspot_api_base_url: str = "https://api.hubapi.com"
    hubspot_rate_limit_per_second: int = 10
    hubspot_batch_size: int = 100

    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    celery_worker_concurrency: int = 4
    celery_task_soft_time_limit: int = 300
    celery_task_time_limit: int = 600

    # S3-compatible object storage
    s3_endpoint_url: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket_raw: str = "revops-raw-imports"
    s3_bucket_exports: str = "revops-exports"
    s3_region: str = "us-east-1"

    # Scoring engine
    scoring_model_version: str = "1.0.0"
    scoring_batch_size: int = 500
    scoring_shadow_model_version: str = ""
    scoring_hot_threshold: int = 75
    scoring_warm_threshold: int = 50
    scoring_cool_threshold: int = 25

    # CORS
    cors_origins: str = "http://localhost:3000"

    # Rate limiting
    rate_limit_per_minute: int = 100
    rate_limit_burst: int = 200

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str) -> str:
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
