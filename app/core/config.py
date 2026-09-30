import json
import logging
from functools import lru_cache
from typing import Any, List, Optional, Union
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Application settings powered by Pydantic Settings v2.
    Reads from environment variables and an optional .env file.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application Configuration
    APP_NAME: str = "FastAPI Multi-Provider AI Router"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Security Configuration
    API_KEYS: Union[List[str], str] = Field(
        default_factory=list,
        description="List of valid API keys for authenticating incoming client requests."
    )
    CORS_ORIGINS: Union[List[str], str] = Field(
        default_factory=lambda: ["*"],
        description="Allowed CORS origins."
    )

    # Provider API Keys & Base URLs
    OPENAI_API_KEY: Optional[SecretStr] = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    ANTHROPIC_API_KEY: Optional[SecretStr] = None
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com/v1"

    GROQ_API_KEY: Optional[SecretStr] = None
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"

    OPENROUTER_API_KEY: Optional[SecretStr] = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

    # Router Strategy & Circuit Breaker Settings
    DEFAULT_PROVIDER: str = "openai"
    PROVIDER_FALLBACK_ORDER: Union[List[str], str] = Field(
        default_factory=lambda: ["openai", "groq", "anthropic", "openrouter"],
        description="Sequential list of providers to try when primary fails."
    )
    REQUEST_TIMEOUT_SECONDS: float = Field(
        default=30.0,
        description="HTTP client timeout in seconds for upstream LLM provider calls."
    )
    MAX_RETRIES_PER_PROVIDER: int = Field(
        default=1,
        description="Maximum retry attempts on the same provider before triggering fallback."
    )
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = Field(
        default=3,
        description="Number of consecutive failures required to trip the circuit breaker."
    )
    CIRCUIT_BREAKER_RECOVERY_TIME_SECONDS: float = Field(
        default=60.0,
        description="Cooldown duration before an OPEN circuit enters HALF-OPEN probe state."
    )

    @field_validator("API_KEYS", "CORS_ORIGINS", "PROVIDER_FALLBACK_ORDER", mode="after")
    @classmethod
    def parse_to_string_list(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("[") and v.endswith("]"):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(item).strip() for item in parsed if str(item).strip()]
                except Exception:
                    pass
            return [item.strip() for item in v.split(",") if item.strip()]
        if isinstance(v, (list, tuple)):
            return [str(item).strip() for item in v if str(item).strip()]
        return []

    def is_provider_configured(self, provider: str) -> bool:
        """Returns True if an API key is actively set for the given provider."""
        provider_lower = provider.lower()
        key_map = {
            "openai": self.OPENAI_API_KEY,
            "anthropic": self.ANTHROPIC_API_KEY,
            "groq": self.GROQ_API_KEY,
            "openrouter": self.OPENROUTER_API_KEY,
        }
        secret = key_map.get(provider_lower)
        return secret is not None and bool(secret.get_secret_value().strip())

    def get_provider_key(self, provider: str) -> Optional[str]:
        """Safely extracts the plaintext secret key for the requested provider."""
        provider_lower = provider.lower()
        key_map = {
            "openai": self.OPENAI_API_KEY,
            "anthropic": self.ANTHROPIC_API_KEY,
            "groq": self.GROQ_API_KEY,
            "openrouter": self.OPENROUTER_API_KEY,
        }
        secret = key_map.get(provider_lower)
        if secret and secret.get_secret_value().strip():
            return secret.get_secret_value().strip()
        return None

    def get_provider_base_url(self, provider: str) -> str:
        """Returns the clean base URL for the given provider."""
        provider_lower = provider.lower()
        url_map = {
            "openai": self.OPENAI_BASE_URL,
            "anthropic": self.ANTHROPIC_BASE_URL,
            "groq": self.GROQ_BASE_URL,
            "openrouter": self.OPENROUTER_BASE_URL,
        }
        return url_map.get(provider_lower, "").rstrip("/")


@lru_cache()
def get_settings() -> Settings:
    """Cached singleton instance of application settings."""
    return Settings()
