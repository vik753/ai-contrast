# ruff: noqa: RUF001
"""S6-T2 AC5: presets allowlist, model ID grammar, ``base_url`` rules (ADR 0016 point 4)."""

from __future__ import annotations

import pytest
from app.ai.adapters.anthropic import AnthropicAdapter
from app.ai.adapters.openai_compatible import OpenAICompatibleAdapter
from app.ai.factory import provider_for
from app.ai.port import AIProvider
from app.ai.presets import PRESETS, AdapterKind, ConnectionConfigError, PresetId
from pydantic import SecretStr

from tests.ai.helpers import KEY, FakeUpstream, make_provider

URLS = {
    PresetId.ANTHROPIC: "https://api.anthropic.com",
    PresetId.OPENAI: "https://api.openai.com/v1",
    PresetId.GEMINI: "https://generativelanguage.googleapis.com/v1beta/openai/",
    PresetId.MISTRAL: "https://api.mistral.ai/v1",
    PresetId.OPENROUTER: "https://openrouter.ai/api/v1",
}
NON_CUSTOM = [p for p in PresetId if p not in {PresetId.CUSTOM, PresetId.FREE}]
CUSTOM_URL = "https://llm.example.com/v1"


def _build(
    preset: PresetId, model: str = "test-model-1", base_url: str | None = None
) -> AIProvider:
    return provider_for(preset, model, SecretStr(KEY), base_url, transport=FakeUpstream())


def _code(preset: PresetId, model: str = "test-model-1", base_url: str | None = None) -> str:
    with pytest.raises(ConnectionConfigError) as info:
        _build(preset, model, base_url)
    return info.value.code


# --- presets ----------------------------------------------------------------------------------


def test_presets_hold_exactly_the_documented_ids() -> None:
    assert set(PRESETS) == {
        PresetId("free"),
        PresetId("anthropic"),
        PresetId("openai"),
        PresetId("gemini"),
        PresetId("mistral"),
        PresetId("openrouter"),
        PresetId("custom"),
    }


@pytest.mark.parametrize("preset", sorted(URLS))
def test_presets_base_url_is_the_documented_constant(preset: PresetId) -> None:
    assert PRESETS[preset].base_url == URLS[preset]


@pytest.mark.parametrize("preset", [PresetId.FREE, PresetId.CUSTOM])
def test_presets_free_and_custom_have_no_constant_url(preset: PresetId) -> None:
    assert PRESETS[preset].base_url is None


def test_presets_only_anthropic_uses_the_anthropic_adapter() -> None:
    kinds = {p.id: p.adapter for p in PRESETS.values()}

    assert kinds.pop(PresetId.ANTHROPIC) == AdapterKind.ANTHROPIC
    assert set(kinds.values()) == {AdapterKind.OPENAI_COMPATIBLE}


def test_presets_table_is_read_only() -> None:
    with pytest.raises(TypeError):
        PRESETS[PresetId.OPENAI] = PRESETS[PresetId.ANTHROPIC]  # type: ignore[index]


@pytest.mark.parametrize("preset", NON_CUSTOM)
def test_presets_suggested_models_pass_the_model_grammar(preset: PresetId) -> None:
    assert PRESETS[preset].models
    for model in PRESETS[preset].models:
        _build(preset, model)


def test_factory_anthropic_preset_builds_the_anthropic_adapter() -> None:
    provider = _build(PresetId.ANTHROPIC)

    assert isinstance(provider, AnthropicAdapter)
    assert isinstance(provider, AIProvider)


@pytest.mark.parametrize("preset", [p for p in NON_CUSTOM if p is not PresetId.ANTHROPIC])
def test_factory_other_presets_build_the_openai_compatible_adapter(preset: PresetId) -> None:
    provider = _build(preset)

    assert isinstance(provider, OpenAICompatibleAdapter)
    assert isinstance(provider, AIProvider)


def test_factory_custom_preset_builds_the_openai_compatible_adapter() -> None:
    assert isinstance(_build(PresetId.CUSTOM, base_url=CUSTOM_URL), OpenAICompatibleAdapter)


# --- model ID grammar -------------------------------------------------------------------------

VALID_MODELS = [
    "gpt-4o",
    "claude-sonnet-4-5",
    "a",
    "7b",
    "Llama-3.1-8B",
    "meta-llama/llama-3.1-8b-instruct:free",
    "vendor/model@2025-01-01",
    "A.b_c-d",
    "m" * 128,
]
INVALID_MODELS = [
    "",
    "m" * 129,
    "-gpt",
    ".gpt",
    "_gpt",
    "/gpt",
    "@gpt",
    ":gpt",
    "gpt 4",
    "gpt\n",
    "gpt\r",
    "gpt\t4",
    "\ngpt",
    "gpt?x=1",
    "gpt#frag",
    "gpt%2e%2e",
    "gpt;rm",
    "gpt\\x",
    'gpt"x',
    "gpt<x>",
    "gpt{x}",
    "gpt$(x)",
    "gpté",
    "gptа",  # Cyrillic a
    "gpt\u200b",
    "gpt／",  # full-width slash
    "gpt\x00",
    "m" * 127 + "\n",
]


@pytest.mark.parametrize("model", VALID_MODELS)
@pytest.mark.parametrize("preset", [PresetId.ANTHROPIC, PresetId.OPENAI])
def test_model_id_valid_grammar_is_accepted(preset: PresetId, model: str) -> None:
    _build(preset, model)


@pytest.mark.parametrize("model", INVALID_MODELS, ids=lambda m: repr(m)[:30])
@pytest.mark.parametrize("preset", [PresetId.ANTHROPIC, PresetId.OPENAI])
def test_model_id_invalid_grammar_is_refused(preset: PresetId, model: str) -> None:
    assert _code(preset, model) == "invalid_model"


def test_model_id_is_checked_for_custom_too() -> None:
    assert _code(PresetId.CUSTOM, "bad model", CUSTOM_URL) == "invalid_model"


# --- base_url only for custom -----------------------------------------------------------------


@pytest.mark.parametrize("preset", NON_CUSTOM)
@pytest.mark.parametrize("url", [CUSTOM_URL, "", "https://evil.example.com", "http://x"])
def test_base_url_is_refused_for_every_preset_except_custom(preset: PresetId, url: str) -> None:
    assert _code(preset, base_url=url) == "unexpected_base_url"


@pytest.mark.parametrize("preset", NON_CUSTOM)
def test_base_url_equal_to_the_preset_url_is_still_refused(preset: PresetId) -> None:
    assert _code(preset, base_url=URLS[preset]) == "unexpected_base_url"


@pytest.mark.parametrize("url", [None, ""])
def test_custom_without_a_base_url_is_refused(url: str | None) -> None:
    assert _code(PresetId.CUSTOM, base_url=url) == "invalid_base_url"


@pytest.mark.parametrize(
    "url",
    [
        "https://llm.example.com",
        "https://llm.example.com/",
        "https://llm.example.com/v1",
        "https://llm.example.com/v1/",
        "https://llm.example.com:443/v1",
        "https://LLM.Example.COM/v1",
        "https://api.eu-west.example.co.uk/openai/v1",
        "https://a.b/v1",
        "https://xn--e1afmkfd.example.com/v1",
        "https://llm.example.com/a_b.c~d-e/f",
        "https://llm.example.com/" + "a" * 255,
    ],
)
def test_custom_base_url_valid_syntax_is_accepted(url: str) -> None:
    _build(PresetId.CUSTOM, base_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "http://llm.example.com/v1",
        "HTTP://llm.example.com/v1",
        "ftp://llm.example.com/v1",
        "//llm.example.com/v1",
        "llm.example.com/v1",
        "https:///v1",
        "https://",
        "https://user@llm.example.com/v1",
        "https://user:pass@llm.example.com/v1",
        "https://:@llm.example.com/v1",
        "https://llm.example.com/v1?x=1",
        "https://llm.example.com/v1?",
        "https://llm.example.com?x=1",
        "https://llm.example.com/v1#frag",
        "https://llm.example.com/v1#",
        "https://llm.example.com:8443/v1",
        "https://llm.example.com:80/v1",
        "https://llm.example.com:0/v1",
        "https://llm.example.com:abc/v1",
        "https://93.184.216.34/v1",
        "https://127.0.0.1/v1",
        "https://[2606:2800:220:1:248:1893:25c8:1946]/v1",
        "https://[::1]/v1",
        "https://0x7f000001/v1",
        "https://2130706433/v1",
        "https://0177.0.0.1/v1",
        "https://127.1/v1",
        "https://localhost/v1",
        "https://intranet/v1",
        "https://llm/v1",
        "https://.example.com/v1",
        "https://llm..example.com/v1",
        "https://-llm.example.com/v1",
        "https://llm_x.example.com/v1",
        "https://lлm.example.com/v1",  # non-ASCII host
        "https://llm.example.com/v1/ü",
        "https://llm.example.com/v1 x",
        "https://llm.example.com/v1\n",
        "https://llm.example.com/v1\r\nHost: evil",
        "https://llm.example.com/v1%2e%2e/x",
        "https://llm.example.com/v1;x",
        "https://llm.example.com/v1:x",
        "https://llm.example.com/v1@x",
        "https://llm.example.com/v1\\x",
        "https://llm.example.com/" + "a" * 256,
        " https://llm.example.com/v1",
        "https://llm.example.com/v1 ",
        "https://llm.example.com\\@evil.example.com/v1",
        "https://llm.example.com@evil.example.com/v1",
    ],
    ids=lambda u: repr(u)[:50],
)
def test_custom_base_url_invalid_syntax_is_refused(url: str) -> None:
    assert _code(PresetId.CUSTOM, base_url=url) == "invalid_base_url"


def test_config_error_has_no_text_beyond_its_code() -> None:
    with pytest.raises(ConnectionConfigError) as info:
        _build(PresetId.CUSTOM, base_url="https://user:SECRETPASS@llm.example.com/v1")

    assert "SECRETPASS" not in str(info.value)
    assert "SECRETPASS" not in repr(info.value)
    assert "SECRETPASS" not in repr(info.value.args)


def test_factory_does_not_keep_the_key_in_a_readable_repr() -> None:
    provider, _ = make_provider()

    assert KEY not in repr(provider)
    assert KEY not in str(provider)
