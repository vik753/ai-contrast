# S6-T2 tests: public names fixed for the implementation

Tests are written from `docs/agent/TASKS.md` S6-T2 and ADR 0016 points 2-5 and 10.
The implementation must use these names. Run: `cd backend && uv run --locked pytest tests/ai -q`.

## `app/ai/port.py`

- `AIErrorCode(enum.StrEnum)`: `provider_auth_failed`, `provider_model_not_found`,
  `provider_rate_limited`, `provider_bad_request`, `provider_unavailable`,
  `provider_blocked_host`, `provider_bad_response`. Member names: the upper-case value.
- `AIError(Exception)`: `AIError(code: AIErrorCode)`, attribute `.code`, `str(err) == code.value`,
  no other text. Always raised with `from None`.
- `CheckResult`: frozen dataclass with one field `ok: bool`. `check()` returns `CheckResult(ok=True)`
  or raises `AIError`. It never returns model text.
- `ModelJson`: type alias `dict[str, object]` (the parsed JSON object).
- `AIRequest`: frozen dataclass, fields `template: PromptTemplate`, `document: PseudonymizedDocument`,
  `schema: type[BaseModel]`, `max_tokens: int`, `text: PseudonymizedText | None = None`,
  `topic: ConfirmedTopic | None = None`. `__post_init__` raises `TypeError` for a wrong type
  (a `str` template, a non-gate document, a schema that is not a `BaseModel` subclass) and
  `ValueError` unless `1 <= max_tokens <= 16384`.
- `AIProvider`: `runtime_checkable` Protocol: `async check() -> CheckResult`,
  `async complete_json(request: AIRequest) -> ModelJson`.

## `app/ai/prompts/__init__.py`

- `PromptTemplate(enum.Enum)` (not a `str` subclass). `.value` is the constant instruction text.
  At least one member. `PromptTemplate("any other string")` raises `ValueError`.

## `app/ai/prompting.py`

- `Message`: frozen dataclass `role: Literal["system", "user"]`, `content: str`.
- `build_messages(request: AIRequest) -> tuple[Message, ...]`: first message is the only
  `system` message and holds `request.template.value`; the others are `user` messages that hold
  the data blocks. Every block is wrapped in a begin and an end delimiter that both contain
  the same nonce `secrets.token_hex(16)` (call it as `secrets.token_hex(16)` through the module
  so tests can patch it). The nonce is drawn after the text is known and drawn again when it occurs
  in the block text; after 8 colliding draws: `AIError(provider_bad_request)`.

## `app/ai/presets.py`

- `PresetId(enum.StrEnum)`: `free`, `anthropic`, `openai`, `gemini`, `mistral`, `openrouter`, `custom`.
- `AdapterKind(enum.StrEnum)`: `anthropic`, `openai_compatible`.
- `Preset`: frozen dataclass `id: PresetId`, `adapter: AdapterKind`, `base_url: str | None`,
  `models: tuple[str, ...]` (suggestions, each valid under the model grammar; `free` is exempt).
  `base_url` is `None` for `free` (T4 builds it) and `custom`.
- `PRESETS: Mapping[PresetId, Preset]`, read-only (`types.MappingProxyType`).
- `ConnectionConfigError(Exception)`: attribute `.code` in `invalid_model`, `unexpected_base_url`,
  `invalid_base_url`. Raised by `provider_for`.

## `app/ai/factory.py`

- `provider_for(preset: PresetId, model: str, key: SecretStr, base_url: str | None = None, *, transport=None) -> AIProvider`.
  Validates model ID and base URL (errors: `ConnectionConfigError`). Creates no SDK client
  until `check()` / `complete_json()` runs; each call builds its own SDK client and closes it.
  `transport` is a test-only hook (an `httpx2` transport); without it the guarded client of
  `app/net/` is used. The 3xx refusal and the 2 MiB cap also apply when `transport` is given.
- Adapters: `app.ai.adapters.anthropic.AnthropicAdapter`,
  `app.ai.adapters.openai_compatible.OpenAICompatibleAdapter`.

## AST policy scope (`test_ai_policy.py`)

Public functions and methods (name without leading `_`) of every module under `app/ai/` take only
gate types, `AIRequest`, `PromptTemplate`, enums, `int`, `bool`, `float`. Exempt: all of
`factory.py` and `presets.py` (connection settings, no contract content), and `__init__` of the
adapter classes. Private helpers (`_name`) are not checked. The old
`test_policy_app_ai_modules_accept_only_gate_types_enums_and_constants` in `test_safety_policy.py`
is replaced by this scope.

## Log config

`log_config.json` sets the loggers `anthropic` and `openai` to `WARNING`. The adapters keep
these levels at `WARNING` even when `ANTHROPIC_LOG` / `OPENAI_LOG` is set.
