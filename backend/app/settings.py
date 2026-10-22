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

from app.extraction.model import (
    DEFAULT_MAX_BLOCKS,
    DEFAULT_MAX_DOCX_ELEMENTS,
    DEFAULT_MAX_DOCX_PART_BYTES,
    DEFAULT_MAX_DOCX_XML_DEPTH,
    DEFAULT_MAX_PDF_PAGES,
    DEFAULT_MAX_PDF_PREV_CHAIN,
    DEFAULT_MAX_TEXT_CHARS,
    DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES,
    MIB,
)

DEFAULT_ALLOWED_ORIGINS = ["http://localhost:5173"]


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
      after the grace period.
    - ``EXTRACT_RATE_GRACE_SECONDS``: grace period before the minimum rate applies
      (a positive, finite number of seconds).

    Parsing sandbox and text caps (positive integers, threat model T4 and T6,
    ADR 0011):

    - ``EXTRACT_WORKER_MEMORY_MB``: address space limit of one parsing child, in MiB.
    - ``EXTRACT_WORKER_CPU_SECONDS``: CPU time limit of one parsing child.
    - ``EXTRACT_WORKER_WALL_SECONDS``: wall-clock deadline of one parsing child.
    - ``EXTRACT_MAX_RESULT_BYTES``: size of the child's JSON result.
    - ``EXTRACT_MAX_TEXT_CHARS``: characters of extracted text of one file.
    - ``EXTRACT_MAX_BLOCKS``: text blocks of one file.
    - ``EXTRACT_SEND_TIMEOUT_SECONDS``: deadline to send the response of
      ``POST /api/extract``; a client that does not read is cut off.

    DOCX extraction (positive integers, threat model T4 and T5, S3-T2):

    - ``MAX_DOCX_PART_BYTES``: real uncompressed size of one archive part. The
      total of all parts is capped by ``MAX_ZIP_UNCOMPRESSED_BYTES``.
    - ``MAX_DOCX_XML_DEPTH``: element nesting depth of one XML part.
    - ``MAX_DOCX_ELEMENTS``: XML elements of all parts of one document.

    PDF extraction (positive integers, threat model T4 and T5, S3-T3):

    - ``MAX_PDF_PAGES``: pages of one PDF, checked before extraction.
    - ``MAX_PDF_PREV_CHAIN``: ``/Prev`` links of the cross-reference chain.

    Google Docs by public link (positive, finite numbers of seconds, S3-T6, ADR 0012):

    - ``GOOGLE_FETCH_TIMEOUT_SECONDS``: total deadline of one fetch, redirects included.
    - ``GOOGLE_CONNECT_TIMEOUT_SECONDS``: DNS and connect timeout of one connection.
    - ``GOOGLE_BODY_TIMEOUT_SECONDS``: deadline to read the small JSON request body of
      ``POST /api/extract/google-doc`` (under the extraction slot).
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
    max_zip_uncompressed_bytes: PositiveInt = DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES
    max_zip_ratio: PositiveInt = 200
    extract_body_timeout_seconds: PositiveInt = 60
    extract_min_rate_bytes_per_second: PositiveInt = 32 * 1024
    extract_rate_grace_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 5.0
    extract_worker_memory_mb: PositiveInt = 192
    extract_worker_cpu_seconds: PositiveInt = 20
    extract_worker_wall_seconds: PositiveInt = 30
    extract_max_result_bytes: PositiveInt = 4 * MIB
    extract_max_text_chars: PositiveInt = DEFAULT_MAX_TEXT_CHARS
    extract_max_blocks: PositiveInt = DEFAULT_MAX_BLOCKS
    extract_send_timeout_seconds: PositiveInt = 30
    max_docx_part_bytes: PositiveInt = DEFAULT_MAX_DOCX_PART_BYTES
    max_docx_xml_depth: PositiveInt = DEFAULT_MAX_DOCX_XML_DEPTH
    max_docx_elements: PositiveInt = DEFAULT_MAX_DOCX_ELEMENTS
    max_pdf_pages: PositiveInt = DEFAULT_MAX_PDF_PAGES
    max_pdf_prev_chain: PositiveInt = DEFAULT_MAX_PDF_PREV_CHAIN
    google_fetch_timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 20.0
    google_connect_timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 5.0
    google_body_timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 5.0

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
