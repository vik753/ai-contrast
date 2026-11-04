"""The adapter factory (ADR 0016 points 3 and 4).

``provider_for`` takes connection settings only (preset, model ID, key, base URL). It builds
no SDK client: each adapter call builds its own and closes it.
"""

from __future__ import annotations

from pydantic import SecretStr

from app.ai.adapters.anthropic import AnthropicAdapter
from app.ai.adapters.openai_compatible import OpenAICompatibleAdapter
from app.ai.port import AIProvider
from app.ai.presets import (
    PRESETS,
    AdapterKind,
    ConnectionConfigError,
    PresetId,
    checked_base_url,
    checked_model,
)
from app.net.ai_client import AITransport

__all__ = ["provider_for"]


def provider_for(
    preset: PresetId,
    model: str,
    key: SecretStr,
    base_url: str | None = None,
    *,
    transport: AITransport | None = None,
) -> AIProvider:
    """Return the provider for a preset. ``transport`` is a test-only hook."""
    entry = PRESETS[preset]
    checked_model(model)
    if preset is PresetId.CUSTOM:
        url = checked_base_url(base_url)
    elif base_url is not None:
        raise ConnectionConfigError("unexpected_base_url") from None
    elif entry.base_url is None:
        # ``free``: its URL is built by the free mode (S6-T4), not here.
        raise ConnectionConfigError("invalid_base_url") from None
    else:
        url = entry.base_url
    if entry.adapter is AdapterKind.ANTHROPIC:
        return AnthropicAdapter(model, key, url, transport)
    return OpenAICompatibleAdapter(
        model, key, url, transport, completion_tokens_field=preset is PresetId.OPENAI
    )
