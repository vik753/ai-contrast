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
    free_base_url,
)
from app.net.ai_client import AITransport

__all__ = ["provider_for"]


def provider_for(  # noqa: PLR0913 - connection settings, all keyword or plain data
    preset: PresetId,
    model: str,
    key: SecretStr,
    base_url: str | None = None,
    *,
    transport: AITransport | None = None,
    free_account_id: str | None = None,
    allow_private: bool = False,
) -> AIProvider:
    """Return the provider for a preset.

    ``free_account_id`` is the operator's Cloudflare account ID; only ``free`` uses it, and
    its URL is built from nothing else. ``allow_private`` (development only) relaxes the
    custom URL syntax; the caller then also passes a transport without the SSRF guard.
    ``transport`` is a test hook, or the development transport.
    """
    entry = PRESETS[preset]
    # The free model is fixed in the preset table (its "@" start is outside the client grammar).
    model = entry.models[0] if preset is PresetId.FREE else checked_model(model)
    if preset is PresetId.CUSTOM:
        url = checked_base_url(base_url, allow_private=allow_private)
    elif base_url is not None:
        raise ConnectionConfigError("unexpected_base_url") from None
    elif entry.base_url is None:
        # ``free``: the URL comes from the operator's account ID, never from a request.
        if free_account_id is None:
            raise ConnectionConfigError("invalid_base_url") from None
        url = free_base_url(free_account_id)
    else:
        url = entry.base_url
    if entry.adapter is AdapterKind.ANTHROPIC:
        return AnthropicAdapter(model, key, url, transport)
    return OpenAICompatibleAdapter(
        model, key, url, transport, completion_tokens_field=preset is PresetId.OPENAI
    )
