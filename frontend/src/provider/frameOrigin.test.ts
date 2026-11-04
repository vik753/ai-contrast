import { afterEach, describe, expect, it, vi } from "vitest";
import { getFrameOrigin } from "./frameOrigin";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("getFrameOrigin", () => {
  it("test_dev_fallback_and_http_allowed_in_dev", () => {
    vi.stubEnv("VITE_TURNSTILE_FRAME_ORIGIN", "");
    expect(getFrameOrigin()).toBe("http://localhost:5174");
    vi.stubEnv("VITE_TURNSTILE_FRAME_ORIGIN", "http://localhost:5174");
    expect(getFrameOrigin()).toBe("http://localhost:5174");
  });
  it("test_production_requires_https", () => {
    vi.stubEnv("DEV", false);
    vi.stubEnv("VITE_TURNSTILE_FRAME_ORIGIN", "http://frame.example.test");
    expect(() => getFrameOrigin()).toThrow();
    vi.stubEnv("VITE_TURNSTILE_FRAME_ORIGIN", "");
    expect(() => getFrameOrigin()).toThrow();
    vi.stubEnv("VITE_TURNSTILE_FRAME_ORIGIN", "https://frame.example.test");
    expect(getFrameOrigin()).toBe("https://frame.example.test");
  });
});
