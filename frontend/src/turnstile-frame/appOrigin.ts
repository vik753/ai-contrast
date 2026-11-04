/** Exact app origin that may receive the token. https only in production. */
export function resolveAppOrigin(env: {
  DEV?: boolean;
  VITE_TURNSTILE_APP_ORIGIN?: string;
}): string {
  const raw = env.VITE_TURNSTILE_APP_ORIGIN ?? "";
  if (raw === "") {
    if (env.DEV === true) return "http://localhost:5173";
    throw new Error("VITE_TURNSTILE_APP_ORIGIN is required in production");
  }
  const url = new URL(raw);
  if (url.origin !== raw) throw new Error("VITE_TURNSTILE_APP_ORIGIN must be an exact origin");
  if (env.DEV !== true && url.protocol !== "https:") {
    throw new Error("VITE_TURNSTILE_APP_ORIGIN must be https in production");
  }
  return raw;
}
