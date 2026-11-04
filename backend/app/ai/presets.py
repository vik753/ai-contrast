"""Provider presets (an allowlist) and connection settings checks (ADR 0016 point 4).

This module and ``factory.py`` take connection settings (model ID, base URL), never content.
"""

from __future__ import annotations

import enum
import ipaddress
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from app.net.guard import BlockedHostError, check_hostname

__all__ = [
    "PRESETS",
    "AdapterKind",
    "ConnectionConfigError",
    "Preset",
    "PresetId",
    "checked_base_url",
    "checked_model",
    "free_base_url",
    "is_ip_literal_url",
]

_MODEL_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}", re.ASCII)
_PRINTABLE_RE: Final = re.compile(r"[\x21-\x7e]+", re.ASCII)
_PATH_RE: Final = re.compile(r"(?:/[A-Za-z0-9._~-]*)*", re.ASCII)
_MAX_PATH: Final = 256
_SCHEME: Final = "https://"
_HTTPS_PORT: Final = "443"
_FREE_URL: Final = "https://api.cloudflare.com/client/v4/accounts/{}/ai/v1"
_ACCOUNT_ID_RE: Final = re.compile(r"[0-9a-f]{32}", re.ASCII)
# Development only (``ALLOW_PRIVATE_PROVIDER_URLS``): a host name or IP literal, any port.
_PRIVATE_AUTHORITY_RE: Final = re.compile(
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:.]{2,45}\])(?::[0-9]{1,5})?",
    re.ASCII,
)


class PresetId(enum.StrEnum):
    FREE = "free"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"
    MISTRAL = "mistral"
    OPENROUTER = "openrouter"
    CUSTOM = "custom"


class AdapterKind(enum.StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai_compatible"


@dataclass(frozen=True)
class Preset:
    id: PresetId
    adapter: AdapterKind
    base_url: str | None
    models: tuple[str, ...]


class ConnectionConfigError(Exception):
    """A model ID or base URL is refused. It holds the code and no other text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _openai(preset: PresetId, base_url: str | None, *models: str) -> Preset:
    return Preset(preset, AdapterKind.OPENAI_COMPATIBLE, base_url, models)


PRESETS: Final[Mapping[PresetId, Preset]] = MappingProxyType(
    {
        PresetId.FREE: _openai(PresetId.FREE, None, "@cf/openai/gpt-oss-120b"),
        PresetId.ANTHROPIC: Preset(
            PresetId.ANTHROPIC,
            AdapterKind.ANTHROPIC,
            "https://api.anthropic.com",
            ("claude-sonnet-4-5", "claude-haiku-4-5"),
        ),
        PresetId.OPENAI: _openai(
            PresetId.OPENAI, "https://api.openai.com/v1", "gpt-4o", "gpt-4o-mini"
        ),
        PresetId.GEMINI: _openai(
            PresetId.GEMINI,
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        ),
        PresetId.MISTRAL: _openai(
            PresetId.MISTRAL,
            "https://api.mistral.ai/v1",
            "mistral-small-latest",
            "mistral-large-latest",
        ),
        PresetId.OPENROUTER: _openai(
            PresetId.OPENROUTER,
            "https://openrouter.ai/api/v1",
            "openai/gpt-4o-mini",
            "anthropic/claude-sonnet-4.5",
        ),
        PresetId.CUSTOM: _openai(PresetId.CUSTOM, None),
    }
)


def checked_model(model: str) -> str:
    """Return the model ID when it fits the grammar, else raise ``invalid_model``."""
    if not _MODEL_RE.fullmatch(model):
        raise ConnectionConfigError("invalid_model") from None
    return model


def free_base_url(account_id: str) -> str:
    """The URL of the free preset. It is built only from the operator's account ID."""
    if not _ACCOUNT_ID_RE.fullmatch(account_id):
        raise ConnectionConfigError("invalid_base_url") from None
    return _FREE_URL.format(account_id)


def is_ip_literal_url(url: str) -> bool:
    """Is the host of an ``https://`` URL an IPv4 or IPv6 literal? Syntax only, no lookup."""
    if not url.startswith(_SCHEME):
        return False
    authority = url[len(_SCHEME) :].split("/", 1)[0]
    if authority.startswith("["):
        host = authority[1:].split("]", 1)[0]
    else:
        host = authority.split(":", 1)[0]
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _checked_private_url(url: str | None) -> str:
    """Development only: ``http`` or ``https``, a name or IP literal, any port."""
    if not url or not _PRINTABLE_RE.fullmatch(url) or "?" in url or "#" in url:
        raise ConnectionConfigError("invalid_base_url") from None
    scheme, sep, rest = url.partition("://")
    authority, slash, tail = rest.partition("/")
    path = slash + tail
    segments = path.split("/")[1:]
    if (
        scheme not in {"http", "https"}
        or not sep
        or not _PRIVATE_AUTHORITY_RE.fullmatch(authority)
        or len(path) > _MAX_PATH
        or not _PATH_RE.fullmatch(path)
        or any(segment in {".", ".."} for segment in segments)
    ):
        raise ConnectionConfigError("invalid_base_url") from None
    return f"{scheme}://{authority}{path}".rstrip("/")


def checked_base_url(url: str | None, *, allow_private: bool = False) -> str:
    """Syntax check of a custom base URL (ADR 0016 point 4); return the normalized URL.

    The addresses are checked later, by the guard at connect time. ``allow_private`` is the
    development switch ``ALLOW_PRIVATE_PROVIDER_URLS``: it allows ``http``, IP literals and
    any port, and the caller must also use a transport without the guard.
    """
    if allow_private:
        return _checked_private_url(url)
    if not url or not _PRINTABLE_RE.fullmatch(url) or not url.startswith(_SCHEME):
        raise ConnectionConfigError("invalid_base_url") from None
    if "?" in url or "#" in url:
        raise ConnectionConfigError("invalid_base_url") from None
    rest = url[len(_SCHEME) :]
    authority, slash, tail = rest.partition("/")
    path = slash + tail
    host, colon, port = authority.partition(":")
    segments = path.split("/")[1:]
    try:
        # The same host rule as the guard (labels, TLD, length); addresses are checked at connect.
        name = check_hostname(host)
    except BlockedHostError:
        raise ConnectionConfigError("invalid_base_url") from None
    if (
        (colon and port != _HTTPS_PORT)
        or len(path) > _MAX_PATH
        or not _PATH_RE.fullmatch(path)
        or any(segment in {".", ".."} for segment in segments)
    ):
        raise ConnectionConfigError("invalid_base_url") from None
    return f"{_SCHEME}{name}{path}".rstrip("/")
