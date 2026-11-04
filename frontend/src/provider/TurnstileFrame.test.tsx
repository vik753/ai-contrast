/** S6-T5 AC3 — app side of the Turnstile frame (ADR 0016 point 7). */
import { act, render } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FRAME_ORIGIN } from "../test/provider-fakes";

interface Props {
  onToken: (t: string) => void;
  resetSignal?: number;
}

async function load(): Promise<ComponentType<Props>> {
  vi.resetModules();
  vi.stubEnv("VITE_TURNSTILE_FRAME_ORIGIN", FRAME_ORIGIN);
  const mod = (await import("./TurnstileFrame")) as { TurnstileFrame: ComponentType<Props> };
  return mod.TurnstileFrame;
}

function post(data: unknown, origin: string, source: MessageEventSource | null): void {
  act(() => {
    window.dispatchEvent(new MessageEvent("message", { data, origin, source }));
  });
}

function requireWindow(w: Window | null | undefined): Window {
  if (!w) throw new Error("no contentWindow");
  return w;
}

beforeEach(() => {
  vi.unstubAllEnvs();
});
afterEach(() => {
  vi.unstubAllEnvs();
});

describe("TurnstileFrame (S6-T5 AC3)", () => {
  it("test_iframe_has_sandbox_frame_origin_src_and_no_referrer", async () => {
    const TurnstileFrame = await load();
    const { container } = render(<TurnstileFrame onToken={vi.fn()} />);
    const f = container.querySelector("iframe");
    expect(f).not.toBeNull();
    expect(f?.getAttribute("src")).toBe(`${FRAME_ORIGIN}/turnstile.html`);
    expect(new Set((f?.getAttribute("sandbox") ?? "").split(/\s+/))).toEqual(
      new Set(["allow-scripts", "allow-same-origin"]),
    );
    expect(f?.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(f?.getAttribute("title")?.length).toBeGreaterThan(0);
  });

  it("test_valid_message_calls_on_token", async () => {
    const TurnstileFrame = await load();
    const onToken = vi.fn();
    const { container } = render(<TurnstileFrame onToken={onToken} />);
    const win = container.querySelector("iframe")?.contentWindow ?? null;
    post({ type: "turnstile-token", token: "tok-1" }, FRAME_ORIGIN, win);
    expect(onToken).toHaveBeenCalledExactlyOnceWith("tok-1");
  });

  it.each([
    ["other origin", { type: "turnstile-token", token: "t" }, "https://evil.example.test"],
    ["app origin", { type: "turnstile-token", token: "t" }, "http://localhost:3000"],
    ["null origin", { type: "turnstile-token", token: "t" }, "null"],
    ["origin prefix", { type: "turnstile-token", token: "t" }, `${FRAME_ORIGIN}.evil.test`],
    ["wrong type", { type: "other", token: "t" }, FRAME_ORIGIN],
    ["extra key", { type: "turnstile-token", token: "t", x: 1 }, FRAME_ORIGIN],
    ["non-string token", { type: "turnstile-token", token: 1 }, FRAME_ORIGIN],
    ["token too long", { type: "turnstile-token", token: "a".repeat(2049) }, FRAME_ORIGIN],
    ["string data", "turnstile-token", FRAME_ORIGIN],
  ])("test_message_with_%s_is_ignored", async (_n, data, origin) => {
    const TurnstileFrame = await load();
    const onToken = vi.fn();
    const { container } = render(<TurnstileFrame onToken={onToken} />);
    post(data, origin, container.querySelector("iframe")?.contentWindow ?? null);
    expect(onToken).not.toHaveBeenCalled();
  });

  it.each([
    ["the app window", () => window],
    ["null", () => null],
  ])("test_message_from_%s_with_right_origin_is_ignored", async (_n, source) => {
    const TurnstileFrame = await load();
    const onToken = vi.fn();
    render(<TurnstileFrame onToken={onToken} />);
    post({ type: "turnstile-token", token: "t" }, FRAME_ORIGIN, source());
    expect(onToken).not.toHaveBeenCalled();
  });

  it("test_message_from_another_iframe_with_right_origin_is_ignored", async () => {
    const TurnstileFrame = await load();
    const onToken = vi.fn();
    render(<TurnstileFrame onToken={onToken} />);
    const other = document.createElement("iframe");
    document.body.append(other);
    post({ type: "turnstile-token", token: "t" }, FRAME_ORIGIN, other.contentWindow);
    other.remove();
    expect(onToken).not.toHaveBeenCalled();
  });

  it("test_reset_signal_posts_reset_to_exact_frame_origin", async () => {
    const TurnstileFrame = await load();
    const { container, rerender } = render(<TurnstileFrame onToken={vi.fn()} resetSignal={0} />);
    const win = container.querySelector("iframe")?.contentWindow;
    const spy = vi.spyOn(requireWindow(win), "postMessage").mockImplementation(() => undefined);
    rerender(<TurnstileFrame onToken={vi.fn()} resetSignal={1} />);
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy.mock.calls[0]?.[0]).toEqual({ type: "reset" });
    expect(spy.mock.calls[0]?.[1]).toBe(FRAME_ORIGIN);
  });

  it("test_listener_is_removed_on_unmount", async () => {
    const TurnstileFrame = await load();
    const onToken = vi.fn();
    const { container, unmount } = render(<TurnstileFrame onToken={onToken} />);
    const win = container.querySelector("iframe")?.contentWindow ?? null;
    unmount();
    post({ type: "turnstile-token", token: "t" }, FRAME_ORIGIN, win);
    expect(onToken).not.toHaveBeenCalled();
  });
});
