"""Provider presets (an allowlist) and connection settings checks (ADR 0016 point 4).

This module and ``factory.py`` take connection settings (model ID, base URL), never content.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

__all__ = [
    "PRESETS",
    "AdapterKind",
    "ConnectionConfigError",
    "Preset",
    "PresetId",
    "checked_base_url",
    "checked_model",
]

_MODEL_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}", re.ASCII)
# Syntax only: at least two labels, a TLD that starts with a letter (so no IP form such as
# ``127.1``). The guard applies the full host rules (ADR 0012) at connect time.
_HOST_RE: Final = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}", re.ASCII
)
_MAX_HOST: Final = 253
_PRINTABLE_RE: Final = re.compile(r"[\x21-\x7e]+", re.ASCII)
_PATH_RE: Final = re.compile(r"(?:/[A-Za-z0-9._~-]*)*", re.ASCII)
_MAX_PATH: Final = 256
_SCHEME: Final = "https://"
_HTTPS_PORT: Final = "443"


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


def checked_base_url(url: str | None) -> str:
    """Syntax check of a custom base URL (ADR 0016 point 4); return the normalized URL.

    The addresses are checked later, by the guard at connect time.
    """
    if not url or not _PRINTABLE_RE.fullmatch(url) or not url.startswith(_SCHEME):
        raise ConnectionConfigError("invalid_base_url") from None
    if "?" in url or "#" in url:
        raise ConnectionConfigError("invalid_base_url") from None
    rest = url[len(_SCHEME) :]
    authority, slash, tail = rest.partition("/")
    path = slash + tail
    host, colon, port = authority.partition(":")
    segments = path.split("/")[1:]
    name = host.lower()
    if (
        len(name) > _MAX_HOST
        or not _HOST_RE.fullmatch(name)
        or (colon and port != _HTTPS_PORT)
        or len(path) > _MAX_PATH
        or not _PATH_RE.fullmatch(path)
        or any(segment in {".", ".."} for segment in segments)
    ):
        raise ConnectionConfigError("invalid_base_url") from None
    return f"{_SCHEME}{name}{path}".rstrip("/")
