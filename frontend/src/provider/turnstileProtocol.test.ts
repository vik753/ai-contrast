/** S6-T5 AC3 — strict message shape (ADR 0016 point 7). */
import { describe, expect, it } from "vitest";
import {
  MAX_TOKEN_LENGTH,
  RESET_MESSAGE,
  TOKEN_MESSAGE_TYPE,
  isResetMessage,
  parseTokenMessage,
} from "./turnstileProtocol";

describe("turnstile protocol (S6-T5 AC3)", () => {
  it("test_constants_match_the_adr", () => {
    expect(TOKEN_MESSAGE_TYPE).toBe("turnstile-token");
    expect(MAX_TOKEN_LENGTH).toBe(2048);
    expect(RESET_MESSAGE).toEqual({ type: "reset" });
  });

  it("test_parse_accepts_exact_shape", () => {
    expect(parseTokenMessage({ type: "turnstile-token", token: "abc" })).toBe("abc");
    expect(parseTokenMessage({ type: "turnstile-token", token: "a".repeat(2048) })).toHaveLength(
      2048,
    );
  });

  it.each([
    ["null", null],
    ["string", "turnstile-token"],
    ["array", ["turnstile-token", "abc"]],
    ["missing token", { type: "turnstile-token" }],
    ["empty token", { type: "turnstile-token", token: "" }],
    ["number token", { type: "turnstile-token", token: 5 }],
    ["object token", { type: "turnstile-token", token: { a: 1 } }],
    ["too long", { type: "turnstile-token", token: "a".repeat(2049) }],
    ["wrong type", { type: "token", token: "abc" }],
    ["extra key", { type: "turnstile-token", token: "abc", extra: 1 }],
  ])("test_parse_rejects_%s", (_n, data) => {
    expect(parseTokenMessage(data)).toBeNull();
  });

  it("test_is_reset_message_is_exact", () => {
    expect(isResetMessage({ type: "reset" })).toBe(true);
    expect(isResetMessage({ type: "reset", x: 1 })).toBe(false);
    expect(isResetMessage({ type: "other" })).toBe(false);
    expect(isResetMessage("reset")).toBe(false);
    expect(isResetMessage(null)).toBe(false);
  });
});
