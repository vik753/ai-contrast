/** Turnstile site key of the frame page. Development may use Cloudflare's test key, production never. */
export const CLOUDFLARE_TEST_KEY = "1x00000000000000000000AA";

export function resolveSiteKey(env: { DEV?: boolean; VITE_TURNSTILE_SITE_KEY?: string }): string {
  const key = env.VITE_TURNSTILE_SITE_KEY ?? "";
  if (env.DEV === true) return key === "" ? CLOUDFLARE_TEST_KEY : key;
  if (key === "") throw new Error("VITE_TURNSTILE_SITE_KEY is required in production");
  if (/^[123]x0{19,}[A-Za-z]{2}$/.test(key)) {
    throw new Error("a Cloudflare test site key is not allowed in production");
  }
  return key;
}
