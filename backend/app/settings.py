"""Application settings, read from environment variables.

The v1 server needs no secrets, so there is no secret setting here and no `.env` file.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_ALLOWED_ORIGINS = ["http://localhost:5173"]


class Settings(BaseSettings):
    """Runtime configuration.

    Environment variables (case-insensitive):

    - ``ENVIRONMENT``: ``development`` or ``production``.
    - ``ALLOWED_ORIGINS``: comma-separated list of exact CORS origins.
    - ``ALLOW_PRIVATE_PROVIDER_URLS``: allow private provider hosts (local models).
      Development only.
    """

    model_config = SettingsConfigDict(
        env_file=None,
        extra="forbid",
        frozen=True,
    )

    environment: Literal["development", "production"] = "development"
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_ORIGINS)
    )
    allow_private_provider_urls: bool = False

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string (from the environment) or a list."""
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list):
            return [item.strip() if isinstance(item, str) else item for item in value]
        return value

    @field_validator("allowed_origins")
    @classmethod
    def _check_origins(cls, value: list[str]) -> list[str]:
        origins = [origin for origin in value if origin]
        if "*" in origins:
            msg = "wildcard origin is not allowed; list exact origins"
            raise ValueError(msg)
        return origins

    @model_validator(mode="after")
    def _no_private_provider_urls_in_production(self) -> Self:
        if self.environment == "production" and self.allow_private_provider_urls:
            msg = "allow_private_provider_urls must be false in production"
            raise ValueError(msg)
        return self
