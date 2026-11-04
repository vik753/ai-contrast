import i18next from "i18next";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { checkConnection, type CheckResult } from "./checkConnection";
import { getFrameOrigin } from "./frameOrigin";
import { forgetKey, getKey, isRemembered, setKey } from "./keyStore";
import { DEFAULT_PRESET, PRESETS, isPresetId, type PresetId } from "./presets";
import { TurnstileFrame } from "./TurnstileFrame";

type Outcome = CheckResult | null;

/** AI provider settings: preset, model, key, connection test (ADR 0016 point 9). */
export function ProviderSettings() {
  const { t } = useTranslation(undefined, { i18n: i18next });
  const ids = {
    title: useId(),
    preset: useId(),
    model: useId(),
    models: useId(),
    baseUrl: useId(),
    key: useId(),
    remember: useId(),
  };
  const [preset, setPreset] = useState<PresetId>(DEFAULT_PRESET);
  const [models, setModels] = useState<Readonly<Record<string, string>>>({});
  const [baseUrl, setBaseUrl] = useState("");
  const [remember, setRemember] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [busy, setBusy] = useState(false);
  const [frameOn, setFrameOn] = useState(false);
  const [awaiting, setAwaiting] = useState(false);
  const [resetSignal, setResetSignal] = useState(0);

  // The key field is uncontrolled: the key lives in storage, never in React state or the DOM text.
  const keyField = useRef<HTMLInputElement>(null);
  const awaitingRef = useRef(false);
  const tokenRef = useRef<string | null>(null);
  const run = useRef(0);
  const abort = useRef<AbortController | null>(null);

  const isFree = preset === "free";
  const model = models[preset] ?? "";
  const suggestions = PRESETS.find((p) => p.id === preset)?.models ?? [];

  useEffect(() => {
    if (keyField.current) keyField.current.value = getKey(preset) ?? "";
  }, [preset]);

  useEffect(
    () => () => {
      run.current++;
      abort.current?.abort();
    },
    [],
  );

  const setWaiting = (value: boolean) => {
    awaitingRef.current = value;
    setAwaiting(value);
  };

  const finish = (mine: number, result: CheckResult) => {
    if (mine !== run.current) return;
    setBusy(false);
    setOutcome(result);
  };

  const startCheck = (request: Parameters<typeof checkConnection>[0]): Promise<CheckResult> => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    return checkConnection(request, controller.signal);
  };

  const submitToken = async (token: string) => {
    const mine = run.current;
    setWaiting(false);
    tokenRef.current = null;
    setBusy(true);
    const result = await startCheck({ provider: "free", turnstileToken: token });
    // One token, one use: the frame solves a fresh challenge for the next check.
    setResetSignal((n) => n + 1);
    finish(mine, result);
  };

  const onToken = (token: string) => {
    if (awaitingRef.current) {
      void submitToken(token);
    } else {
      tokenRef.current = token;
    }
  };

  const onChoose = (value: string) => {
    if (!isPresetId(value)) return;
    run.current++;
    abort.current?.abort();
    tokenRef.current = null;
    setWaiting(false);
    setBusy(false);
    setFrameOn(false);
    setOutcome(null);
    setRemember(isRemembered(value));
    setPreset(value);
  };

  const onKeyInput = (value: string) => {
    if (value === "") forgetKey(preset);
    else setKey(preset, value, { remember });
  };

  const onRemember = (checked: boolean) => {
    setRemember(checked);
    const key = keyField.current?.value ?? "";
    if (key !== "") setKey(preset, key, { remember: checked });
  };

  const onForget = () => {
    forgetKey(preset);
    if (keyField.current) keyField.current.value = "";
    setRemember(false);
    setOutcome(null);
  };

  const onTest = () => {
    setOutcome(null);
    if (isFree) {
      try {
        getFrameOrigin();
      } catch {
        setOutcome({ ok: false, code: "free_mode_unavailable" });
        return;
      }
      setFrameOn(true);
      const token = tokenRef.current;
      if (token !== null) void submitToken(token);
      else setWaiting(true);
      return;
    }
    const key = (keyField.current?.value ?? "").trim();
    const modelId = model.trim();
    const url = baseUrl.trim();
    const missing =
      key === ""
        ? "invalid_provider_key"
        : modelId === ""
          ? "invalid_model"
          : preset === "custom" && url === ""
            ? "invalid_base_url"
            : null;
    if (missing !== null) {
      setOutcome({ ok: false, code: missing });
      return;
    }
    const mine = ++run.current;
    setBusy(true);
    void startCheck({
      provider: preset,
      model: modelId,
      ...(preset === "custom" ? { baseUrl: url } : {}),
      key,
    }).then((result) => {
      finish(mine, result);
    });
  };

  return (
    <section className="card provider" aria-labelledby={ids.title}>
      <h2 id={ids.title} className="card__title">
        {t("provider.title")}
      </h2>

      <div className="provider__field">
        <label htmlFor={ids.preset} className="provider__label">
          {t("provider.preset.label")}
        </label>
        <select
          id={ids.preset}
          className="provider__input"
          value={preset}
          onChange={(e) => {
            onChoose(e.target.value);
          }}
        >
          {PRESETS.map((p) => (
            <option key={p.id} value={p.id}>
              {t(`provider.preset.${p.id}`)}
            </option>
          ))}
        </select>
      </div>

      {isFree ? (
        <>
          <p className="note">{t("provider.free.notice")}</p>
          <p className="note">{t("provider.free.turnstileNotice")}</p>
        </>
      ) : (
        <>
          {preset === "gemini" ? (
            <>
              <p className="note">{t("provider.gemini.hint")}</p>
              <p className="note provider__warning">{t("provider.gemini.dataUse")}</p>
            </>
          ) : null}

          <div className="provider__field">
            <label htmlFor={ids.model} className="provider__label">
              {t("provider.model.label")}
            </label>
            <input
              id={ids.model}
              className="provider__input"
              type="text"
              list={ids.models}
              autoComplete="off"
              spellCheck={false}
              value={model}
              onChange={(e) => {
                setModels({ ...models, [preset]: e.target.value });
              }}
            />
            <datalist id={ids.models}>
              {suggestions.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </div>

          {preset === "custom" ? (
            <details className="provider__advanced">
              <summary>{t("provider.advanced")}</summary>
              <div className="provider__field">
                <label htmlFor={ids.baseUrl} className="provider__label">
                  {t("provider.baseUrl.label")}
                </label>
                <input
                  id={ids.baseUrl}
                  className="provider__input"
                  type="text"
                  inputMode="url"
                  autoComplete="off"
                  spellCheck={false}
                  value={baseUrl}
                  onChange={(e) => {
                    setBaseUrl(e.target.value);
                  }}
                />
              </div>
            </details>
          ) : null}

          <div className="provider__field">
            <label htmlFor={ids.key} className="provider__label">
              {t("provider.key.label")}
            </label>
            <input
              id={ids.key}
              ref={keyField}
              className="provider__input"
              type="password"
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => {
                onKeyInput(e.target.value);
              }}
            />
          </div>

          <div className="provider__field provider__field--inline">
            <input
              id={ids.remember}
              type="checkbox"
              checked={remember}
              onChange={(e) => {
                onRemember(e.target.checked);
              }}
            />
            <label htmlFor={ids.remember}>{t("provider.remember.label")}</label>
          </div>
          {remember ? (
            <p role="note" className="note provider__warning">
              {t("provider.remember.warning")}
            </p>
          ) : null}
        </>
      )}

      <div className="provider__actions">
        <button type="button" className="button" disabled={busy} onClick={onTest}>
          {t("provider.test.button")}
        </button>
        {isFree ? null : (
          <button type="button" className="button button--quiet" onClick={onForget}>
            {t("provider.forget")}
          </button>
        )}
      </div>

      {awaiting ? <p aria-live="polite">{t("provider.test.waiting")}</p> : null}
      {busy ? <p aria-live="polite">{t("provider.test.checking")}</p> : null}
      {outcome?.ok === true ? (
        <p role="status" className="provider__ok">
          {t("provider.test.ok")}
        </p>
      ) : null}
      {outcome?.ok === false ? (
        <p role="alert" className="provider__error">
          {t(`provider.error.${outcome.code}` as "provider.error.unknown")}
        </p>
      ) : null}

      {isFree && frameOn ? <TurnstileFrame onToken={onToken} resetSignal={resetSignal} /> : null}
    </section>
  );
}
