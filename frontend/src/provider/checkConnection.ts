/**
 * `POST /api/provider/check` (ADR 0016 point 6). The key goes only into `X-Provider-Key`.
 * Server text is never returned: only the closed set of error codes below.
 */
export interface CheckRequest {
  provider: string;
  model?: string;
  baseUrl?: string;
  key?: string;
  turnstileToken?: string;
}

export type CheckResult = { ok: true } | { ok: false; code: string };

/** Codes the server may answer with. `network` and `unknown` are made here only. */
export const SERVER_CODES: ReadonlySet<string> = new Set([
  "request_too_large",
  "invalid_request",
  "invalid_provider",
  "invalid_model",
  "unexpected_model",
  "unexpected_base_url",
  "invalid_base_url",
  "unexpected_turnstile_token",
  "invalid_provider_key",
  "unexpected_provider_key",
  "free_mode_unavailable",
  "turnstile_failed",
  "free_quota_exhausted",
  "rate_limited",
  "busy",
  "provider_auth_failed",
  "provider_model_not_found",
  "provider_rate_limited",
  "provider_bad_request",
  "provider_blocked_host",
  "provider_unavailable",
  "provider_bad_response",
]);

const UNKNOWN: CheckResult = { ok: false, code: "unknown" };

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export async function checkConnection(
  req: CheckRequest,
  signal?: AbortSignal,
): Promise<CheckResult> {
  const body: Record<string, string> = { provider: req.provider };
  if (req.model !== undefined) body.model = req.model;
  if (req.baseUrl !== undefined) body.base_url = req.baseUrl;
  if (req.turnstileToken !== undefined) body.turnstile_token = req.turnstileToken;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (req.key !== undefined) headers["X-Provider-Key"] = req.key;

  let response: Response;
  try {
    response = await fetch("/api/provider/check", {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      credentials: "omit",
      redirect: "error",
      cache: "no-store",
      ...(signal ? { signal } : {}),
    });
  } catch {
    return { ok: false, code: "network" };
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    return UNKNOWN;
  }
  if (!isRecord(data)) return UNKNOWN;
  const keys = Object.keys(data);
  if (response.ok) {
    return keys.length === 1 && data.ok === true ? { ok: true } : UNKNOWN;
  }
  const code = data.error;
  if (keys.length === 1 && typeof code === "string" && SERVER_CODES.has(code)) {
    return { ok: false, code };
  }
  return UNKNOWN;
}
