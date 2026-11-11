from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULTS = {
    "jwt_secret_key": "insecure-dev-jwt-secret-change-me",
    "app_secret_key": "insecure-dev-secret-change-me",
    "admin_password": "change-me-strong-password",
}
MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: Literal["development", "staging", "production"] = "development"
    app_secret_key: str = "insecure-dev-secret-change-me"  # encrypts the CRM tokens stored in the database (changing it makes them unreadable)
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
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)  # cost of hashing a password (4 is only for tests)
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
    scoring_hot_threshold: int = 75
    scoring_warm_threshold: int = 50
    scoring_cool_threshold: int = 25

    # CORS
    cors_origins: str = "http://localhost:3000"

    # Rate limiting (storage defaults to REDIS_URL; use "memory://" for a single process or tests)
    rate_limit_per_minute: int = 100
    rate_limit_burst: int = 200
    rate_limit_login_per_minute: int = 10
    rate_limit_storage_uri: str = ""

    # Salesforce OAuth
    salesforce_client_id: str = ""
    salesforce_client_secret: str = ""
    salesforce_redirect_uri: str = ""
    salesforce_login_url: str = "https://login.salesforce.com"

    # HubSpot webhook secret (for signature verification)
    hubspot_webhook_secret: str = ""  # the HubSpot app's client secret: the deal-won webhook is refused without it
    # The public base URL HubSpot calls (e.g. https://api.example.com), used to check the request signature behind a proxy; defaults to the URL the app sees.
    public_api_url: str = ""

    # Outbound webhooks: by default only public https targets are allowed. Set this to deliver to localhost / private addresses and plain http
    # (for local development against a test receiver; never in production).
    webhook_allow_private_targets: bool = False
    # Salesforce instance URLs must end with one of these (comma-separated); they receive the stored access token.
    salesforce_allowed_domains: str = ".salesforce.com,.force.com"

    # AI Intelligence (Claude API)
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-5-5"
    ai_intelligence_cache_ttl_seconds: int = 21600  # 6 hours
    ai_intelligence_rate_limit_per_minute: int = 10

    # ML Model artifacts directory
    ml_models_dir: str = "data/models"

    @model_validator(mode="after")
    def refuse_insecure_deployment(self) -> "Settings":
        """Outside development the placeholder secrets must be replaced, and credentials may not be shared with every origin."""
        if self.app_env == "development":
            return self
        problems = []
        for name, placeholder in INSECURE_DEFAULTS.items():
            if getattr(self, name) == placeholder:
                problems.append(f"{name.upper()} is still the placeholder value")
        for name in ("jwt_secret_key", "app_secret_key"):
            if len(getattr(self, name)) < MIN_SECRET_LENGTH:
                problems.append(f"{name.upper()} must be at least {MIN_SECRET_LENGTH} characters")
        if "*" in self.cors_origins_list:
            problems.append("CORS_ORIGINS may not be '*' (credentials are allowed)")
        if problems:
            raise ValueError(f"APP_ENV={self.app_env}: " + "; ".join(problems))
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def limiter_storage_uri(self) -> str:
        return self.rate_limit_storage_uri or self.redis_url

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
