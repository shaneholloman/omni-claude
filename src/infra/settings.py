from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.api.routes import Routes
from src.infra.logger import get_logger
from src.models.base_models import Environment

logger = get_logger()


class ServiceType(str, Enum):
    """Type of service being run."""

    API = "api"
    WORKER = "worker"


class Settings(BaseSettings):
    """Settings shared between API and ARQ worker."""

    # General
    project_name: str = Field("kollektiv", description="Project name")

    # Environment configuration
    environment: Environment = Field(Environment.LOCAL, alias="ENVIRONMENT", description="Application environment")

    # Debug mode
    debug: bool = Field(False, description="True if debug mode is enabled", alias="DEBUG")

    # API keys
    firecrawl_api_url: str = Field("https://api.firecrawl.dev/v1", description="Firecrawl API URL")
    firecrawl_api_key: str = Field(..., alias="FIRECRAWL_API_KEY")
    anthropic_api_key: str = Field(..., alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    cohere_api_key: str = Field(..., alias="COHERE_API_KEY")
    weave_project_name: str | None = Field(None, alias="WEAVE_PROJECT_NAME")

    # Server configuration
    api_host: str = Field(
        "127.0.0.1" if Environment.LOCAL else "0.0.0.0",  # noqa: S104, Local uses localhost, others use 0.0.0.0
        alias="API_HOST",
        description="API host - 127.0.0.1 for local, 0.0.0.0 for staging/prod",
    )
    api_port: int = Field(
        default=8080,
        alias="PORT",  # Railway injects PORT environment variable
        description="API port - defaults to 8000, but can be overridden by Railway's PORT variable",
    )
    railway_public_domain: str | None = Field(
        None,
        description="Railway's public domain for staging/prod",
        alias="RAILWAY_PUBLIC_DOMAIN",
    )

    # Crawler configuration
    max_retries: int = Field(3, description="Maximum retries for crawler requests")
    backoff_factor: float = Field(2.0, description="Backoff factor for retries")
    default_page_limit: int = Field(25, description="Default page limit for crawls")
    default_max_depth: int = Field(5, description="Default max depth for crawls")

    # LLM configuration
    main_model: str = Field("claude-3-5-sonnet-20241022", description="Main LLM model")
    evaluator_model_name: str = Field("gpt-4o-mini", description="Evaluator model name")
    embedding_model: str = Field("text-embedding-3-small", description="Embedding model")

    # Base directory is src/
    src_dir: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent)

    # Supabase
    supabase_url: str = Field(..., description="Supabase URL", alias="SUPABASE_URL")
    supabase_service_role_key: str = Field(
        ...,
        description="Kollektiv API uses Supabase service role key for managing the database",
        alias="SUPABASE_SERVICE_KEY",
    )

    # All paths are now relative to src_dir
    eval_dir: Path = Field(default_factory=lambda: Path("src/core/evaluation"))
    prompt_dir: Path = Field(default_factory=lambda: Path("src/core/chat/prompts"))
    prompts_file: str = Field("prompts.yaml", description="Prompt file")
    tools_dir: Path = Field(default_factory=lambda: Path("src/core/chat/tools"))
    tools_file: str = Field("tools.yaml", description="Tools file")

    # Ngrok URL (set by docker-compose in local env)
    ngrok_authtoken: str | None = Field(None, description="Used for local dev only", alias="NGROK_AUTHTOKEN")
    ngrok_url: str | None = Field(None, description="Used for local dev only", alias="NGROK_URL")

    # Monitoring
    logfire_write_token: str | None = Field(
        None, alias="LOGFIRE_TOKEN", description="Logfire write token, optional in CI."
    )
    sentry_dsn: str = Field(
        "https://c2f1acc0646d1578b572e318b6b118d5@o4508393623257088.ingest.us.sentry.io/4508393650847744",
        alias="SENTRY_DSN",
        description="Sentry DSN",
    )

    # Redis setup
    redis_url: str = Field(..., alias="REDIS_URL", description="Redis url")
    redis_user: str | None = Field(None, alias="REDIS_USER", description="Redis user")
    redis_password: str | None = Field(None, alias="REDIS_PASSWORD", description="Redis password")

    # Pub/Sub
    process_documents_channel: str = Field("process_documents", description="Process documents channel")

    # Chroma client
    chroma_private_url: str = Field(
        ...,
        description="Chroma URL exposed by Railway service. Not set locally.",
        alias="CHROMA_PRIVATE_URL",
    )
    chroma_client_auth_credentials: str | None = Field(
        None,
        description="Auth credential for Chroma - username:password",
        alias="CHROMA_CLIENT_AUTH_CREDENTIALS",
    )

    # Add this with other settings
    service: ServiceType = Field(
        ...,  # Make it required
        alias="SERVICE",
        description="Type of service to run (api or worker)",
    )

    @property
    def reload(self) -> bool:
        """Reload the app when code changes."""
        return self.environment == Environment.LOCAL

    @property
    def gunicorn_workers(self) -> int:
        """Get number of Gunicorn workers based on environment.

        Staging: 2 workers for testing
        Production: (2 * cpu_count) + 1 for optimal performance
        """
        if self.environment == Environment.STAGING:
            return 2
        else:
            # Production: Using standard Gunicorn formula (2*CPU)+1
            # Railway provides 8 vCPUs
            # Start with smaller number
            return 4
            # return (2 * cpu_count()) + 1  # 17 workers

    model_config = SettingsConfigDict(
        env_file=os.path.join("config", ".env"),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def public_url(self) -> str:
        """Dynamically generate public URL based on environment."""
        if self.environment == Environment.LOCAL:
            public_url = self.ngrok_url or f"http://{self.api_host}:{self.api_port}"
            logger.debug(f"Using public URL: {public_url}")
            return public_url
        if not self.railway_public_domain:
            raise ValueError("RAILWAY_PUBLIC_DOMAIN must be set in staging/production")
        public_domain = self.railway_public_domain
        logger.debug(f"Using public domain: {public_domain}")
        return f"https://{public_domain}"

    @property
    def firecrawl_webhook_url(self) -> str:
        """Dynamically generates the Firecrawl webhook URL."""
        return f"{self.public_url}{Routes.System.Webhooks.FIRECRAWL}"

    @property
    def redis_host(self) -> str:
        """Parses redis url and returns redis host."""
        parsed_url = urlparse(self.redis_url)
        redis_host = parsed_url.hostname
        if redis_host is None:
            raise ValueError("Redis host is not set")
        return redis_host

    @property
    def redis_port(self) -> int:
        """Parses redis url and returns redis port."""
        parsed_url = urlparse(self.redis_url)
        redis_port = parsed_url.port
        if redis_port is None:
            raise ValueError("Redis port is not set")
        return redis_port


def initialize_settings() -> Settings:
    """Initialize settings."""
    try:
        settings = Settings()
        logger.info("✓ Initialized settings successfully.")
        return settings
    except ValueError as e:
        logger.exception("Environment variables not set.")
        raise ValueError(f"An error occurred during settings loading: {str(e)}") from e
    except Exception as e:
        logger.exception("Error occurred while loading settings")
        raise Exception(f"An error occurred during settings loading: {str(e)}") from e


settings = initialize_settings()


# TODO: implement caching of the settings instance
@lru_cache
def get_settings() -> Settings:
    """Get settings."""
    return settings
