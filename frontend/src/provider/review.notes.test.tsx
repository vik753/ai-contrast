/** S6-T5 review notes: every server code has a message; frame callbacks; invalid frame origin. */
import { act, render } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "../i18n/locales/en.json";
import ru from "../i18n/locales/ru.json";
import uk from "../i18n/locales/uk.json";
import { FRAME_ORIGIN } from "../test/provider-fakes";
import { flattenLocale } from "../test/locale-utils";
import { SERVER_CODES } from "./checkConnection";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("review notes", () => {
  it("test_every_server_code_has_a_message_in_all_languages", () => {
    for (const l of [en, uk, ru]) {
      const flat = flattenLocale(l);
      for (const c of [...SERVER_CODES, "network", "unknown"]) {
        expect(typeof flat[`provider.error.${c}`], c).toBe("string");
      }
    }
  });

  interface Props {
    onToken: (t: string) => void;
    onExpired?: () => void;
    onError?: () => void;
  }
  async function load(): Promise<ComponentType<Props>> {
    vi.resetModules();
    vi.stubEnv("VITE_TURNSTILE_FRAME_ORIGIN", FRAME_ORIGIN);
    return ((await import("./TurnstileFrame")) as { TurnstileFrame: ComponentType<Props> })
      .TurnstileFrame;
  }
  const post = (data: unknown, origin: string, source: MessageEventSource | null) => {
    act(() => {
      window.dispatchEvent(new MessageEvent("message", { data, origin, source }));
    });
  };

  it("test_expired_and_error_callbacks_need_exact_origin_source_and_shape", async () => {
    const F = await load();
    const onExpired = vi.fn();
    const onError = vi.fn();
    const { container } = render(<F onToken={vi.fn()} onExpired={onExpired} onError={onError} />);
    const win = container.querySelector("iframe")?.contentWindow ?? null;
    post({ type: "turnstile-expired" }, "https://evil.example.test", win);
    post({ type: "turnstile-expired" }, FRAME_ORIGIN, window);
    post({ type: "turnstile-error", x: 1 }, FRAME_ORIGIN, win);
    expect(onExpired).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
    post({ type: "turnstile-expired" }, FRAME_ORIGIN, win);
    post({ type: "turnstile-error" }, FRAME_ORIGIN, win);
    expect(onExpired).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it("test_invalid_frame_origin_renders_nothing_without_throwing", async () => {
    const F = await load();
    vi.stubEnv("VITE_TURNSTILE_FRAME_ORIGIN", "not an origin");
    const { container } = render(<F onToken={vi.fn()} />);
    expect(container.querySelector("iframe")).toBeNull();
  });
});
