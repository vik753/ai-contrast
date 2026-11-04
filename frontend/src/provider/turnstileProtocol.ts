/** Messages between the app and the Turnstile frame (ADR 0016 point 7). Strict shapes only. */
export const TOKEN_MESSAGE_TYPE = "turnstile-token";
export const MAX_TOKEN_LENGTH = 2048;
export const EXPIRED_MESSAGE_TYPE = "turnstile-expired";
export const ERROR_MESSAGE_TYPE = "turnstile-error";
/** A token older than this is dropped (Cloudflare tokens live 300 s; the server also checks 300 s). */
export const MAX_TOKEN_AGE_MS = 240_000;
export const RESET_MESSAGE = { type: "reset" } as const;

function exactKeys(data: object, keys: readonly string[]): boolean {
  const own = Object.keys(data);
  return own.length === keys.length && keys.every((k) => own.includes(k));
}

function isRecord(data: unknown): data is Record<string, unknown> {
  return typeof data === "object" && data !== null && !Array.isArray(data);
}

/** The token of a valid token message, else `null`. */
export function parseTokenMessage(data: unknown): string | null {
  if (!isRecord(data) || !exactKeys(data, ["type", "token"])) return null;
  const { type, token } = data;
  if (type !== TOKEN_MESSAGE_TYPE || typeof token !== "string") return null;
  return token.length > 0 && token.length <= MAX_TOKEN_LENGTH ? token : null;
}

export function isResetMessage(data: unknown): boolean {
  return isRecord(data) && exactKeys(data, ["type"]) && data.type === RESET_MESSAGE.type;
}

export function isExpiredMessage(data: unknown): boolean {
  return isRecord(data) && exactKeys(data, ["type"]) && data.type === EXPIRED_MESSAGE_TYPE;
}

export function isErrorMessage(data: unknown): boolean {
  return isRecord(data) && exactKeys(data, ["type"]) && data.type === ERROR_MESSAGE_TYPE;
}

/** True when a token issued at `issuedAt` may still be used at `now` (both in ms). */
export function isTokenFresh(issuedAt: number, now: number): boolean {
  return now >= issuedAt && now - issuedAt <= MAX_TOKEN_AGE_MS;
}
