/** The Trusted Types `default` policy is installed at startup, before the app starts. */
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
  document.body.replaceChildren();
});

describe("main entry", () => {
  it("test_default_policy_is_created_before_start", async () => {
    const order: string[] = [];
    const createPolicy = vi.fn((name: string) => {
      order.push(`policy ${name}`);
      return {};
    });
    vi.stubGlobal("trustedTypes", { createPolicy });
    vi.resetModules();
    vi.doMock("./bootstrap", () => ({
      start: () => {
        order.push("start");
        return Promise.resolve({});
      },
    }));
    const root = document.createElement("div");
    root.id = "root";
    document.body.append(root);
    await import("./main");
    expect(order).toEqual(["policy default", "start"]);
    vi.doUnmock("./bootstrap");
  });
});
