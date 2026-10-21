"""Application settings, read from environment variables.

The v1 server needs no secrets yet, so there is no secret setting here and no `.env`
file. Validation errors never include the rejected values (``hide_input_in_errors``),
so a startup failure cannot print a secret.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import Field, PositiveInt, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_ALLOWED_ORIGINS = ["http://localhost:5173"]

MIB = 1024 * 1024

# An origin is exactly `scheme://host[:port]` (lowercase after normalization).
# Host: a DNS name or IPv4 address, or an IPv6 address in brackets. No userinfo,
# path (not even "/"), query, fragment or wildcard. Non-ASCII hosts must be given
# in punycode, because that is what browsers send in the Origin header.
_ORIGIN_RE = re.compile(
    r"(?P<scheme>https?)://"
    r"(?P<host>[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?|\[[0-9a-f:.]+\])"
    r"(?::(?P<port>[0-9]{1,5}))?"
)
_DEFAULT_PORTS = {"http": 80, "https": 443}
_MAX_PORT = 65535


def _is_control(char: str) -> bool:
    """C0 controls, DEL and C1 controls."""
    code = ord(char)
    return code < 0x20 or 0x7F <= code <= 0x9F  # noqa: PLR2004 - Unicode ranges


def normalize_origin(raw: str) -> str:
    """Return the normalized origin or raise ``ValueError``.

    Error messages never include the value (it may be anything an operator pasted).
    """
    if any(_is_control(char) for char in raw):
        msg = "origin contains control characters"
        raise ValueError(msg)
    value = raw.strip(" ").lower()
    match = _ORIGIN_RE.fullmatch(value)
    if match is None:
        msg = "origin must be exactly scheme://host[:port] with http or https"
        raise ValueError(msg)
    scheme, host, port_text = match.group("scheme", "host", "port")
    origin = f"{scheme}://{host}"
    if port_text is not None:
        port = int(port_text)
        if not 1 <= port <= _MAX_PORT:
            msg = "origin port is out of range"
            raise ValueError(msg)
        # Browsers omit the default port from the Origin header.
        if port != _DEFAULT_PORTS[scheme]:
            origin = f"{origin}:{port}"
    return origin


class Settings(BaseSettings):
    """Runtime configuration.

    Environment variables (case-insensitive):

    - ``ENVIRONMENT``: ``development`` or ``production``.
    - ``ALLOWED_ORIGINS``: comma-separated list of exact CORS origins
      (``scheme://host[:port]``). Required in production, ``https`` only.
    - ``ALLOW_PRIVATE_PROVIDER_URLS``: allow private provider hosts (local models).
      Development only.

    Upload limits (positive integers, threat model T4 and T6, ADR 0010):

    - ``MAX_FILE_BYTES``: body size of ``POST /api/extract`` (one file).
    - ``MAX_JSON_BODY_BYTES``: body size of every other route.
    - ``MAX_CONCURRENT_EXTRACTIONS``: extractions in progress per server.
    - ``MAX_ZIP_ENTRIES``: entries in one ZIP (DOCX) archive.
    - ``MAX_ZIP_UNCOMPRESSED_BYTES``: declared uncompressed size of one archive.
    - ``MAX_ZIP_RATIO``: uncompressed / compressed size of one archive entry.
    - ``EXTRACT_BODY_TIMEOUT_SECONDS``: deadline to receive the whole upload body.
    - ``EXTRACT_MIN_RATE_BYTES_PER_SECOND``: minimum average upload rate, checked
      after a fixed grace period (``app.api.extract.RATE_GRACE_SECONDS``).
    """

    model_config = SettingsConfigDict(
        env_file=None,
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    environment: Literal["development", "production"] = "development"
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_ORIGINS)
    )
    allow_private_provider_urls: bool = False

    max_file_bytes: PositiveInt = 10 * MIB
    max_json_body_bytes: PositiveInt = 64 * 1024
    max_concurrent_extractions: PositiveInt = 2
    max_zip_entries: PositiveInt = 2000
    max_zip_uncompressed_bytes: PositiveInt = 100 * MIB
    max_zip_ratio: PositiveInt = 200
    extract_body_timeout_seconds: PositiveInt = 60
    extract_min_rate_bytes_per_second: PositiveInt = 32 * 1024

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string (from the environment) or a list.

        Empty entries (for example from a trailing comma) are dropped.
        """
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list):
            return [item for item in value if not (isinstance(item, str) and item.strip(" ") == "")]
        return value

    @field_validator("allowed_origins")
    @classmethod
    def _normalize_origins(cls, value: list[str]) -> list[str]:
        origins: list[str] = []
        for raw in value:
            origin = normalize_origin(raw)
            if origin not in origins:
                origins.append(origin)
        return origins

    @model_validator(mode="after")
    def _production_rules(self) -> Self:
        if self.environment != "production":
            return self
        if self.allow_private_provider_urls:
            msg = "allow_private_provider_urls must be false in production"
            raise ValueError(msg)
        if "allowed_origins" not in self.model_fields_set or not self.allowed_origins:
            msg = "allowed_origins must be set explicitly in production"
            raise ValueError(msg)
        if any(not origin.startswith("https://") for origin in self.allowed_origins):
            msg = "allowed_origins must use https in production"
            raise ValueError(msg)
        return self
