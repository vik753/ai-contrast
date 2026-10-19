// @vitest-environment node
/**
 * S1-T2b AC6 (S1-T2 AC9) — the Vite dev server proxies `/api` to
 * `VITE_API_PROXY_TARGET`, default `http://localhost:8000`.
 *
 * `vite.config.ts` is imported fresh for every test (`vi.resetModules`) so
 * that the environment variable is read again.
 */
import type { ConfigEnv, UserConfig } from "vite";
import { afterEach, describe, expect, it, vi } from "vitest";

const ENV_NAME = "VITE_API_PROXY_TARGET";
const SERVE_ENV: ConfigEnv = {
  command: "serve",
  mode: "development",
  isSsrBuild: false,
  isPreview: false,
};

async function loadConfig(): Promise<UserConfig> {
  vi.resetModules();
  const mod: { default: unknown } = await import("../../vite.config");
  const exported = mod.default;
  if (typeof exported === "function") {
    const factory = exported as (env: ConfigEnv) => UserConfig | Promise<UserConfig>;
    return factory(SERVE_ENV);
  }
  return (await exported) as UserConfig;
}

async function apiProxyTarget(): Promise<unknown> {
  const config = await loadConfig();
  const entry = config.server?.proxy?.["/api"];
  if (entry === undefined) {
    throw new Error('vite.config.ts has no server.proxy["/api"]');
  }
  return typeof entry === "string" ? entry : entry.target;
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("Vite /api proxy (S1-T2b AC6)", () => {
  it("test_api_proxy_target_defaults_to_localhost_8000_without_env", async () => {
    vi.stubEnv(ENV_NAME, undefined);
    expect(await apiProxyTarget()).toBe("http://localhost:8000");
  }, 30_000);

  it("test_api_proxy_target_follows_vite_api_proxy_target_env", async () => {
    vi.stubEnv(ENV_NAME, "http://backend:8000");
    expect(await apiProxyTarget()).toBe("http://backend:8000");
  }, 30_000);

  it("test_api_proxy_target_follows_env_change_between_loads", async () => {
    vi.stubEnv(ENV_NAME, "http://127.0.0.1:9000");
    expect(await apiProxyTarget()).toBe("http://127.0.0.1:9000");
    vi.stubEnv(ENV_NAME, undefined);
    expect(await apiProxyTarget()).toBe("http://localhost:8000");
  }, 30_000);
});
