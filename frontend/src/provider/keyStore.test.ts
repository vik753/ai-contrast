/** S6-T5 AC2 — key storage (T1 browser controls, ADR 0016 point 9). */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAllData } from "../storage/historySetting";
import { forgetAllKeys, forgetKey, getKey, isRemembered, setKey } from "./keyStore";

const KEY = "sk-CANARY-4f9a1c";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe("keyStore (S6-T5 AC2)", () => {
  it("test_set_key_default_writes_session_storage_only", () => {
    setKey("openai", KEY, { remember: false });
    expect(sessionStorage.getItem("aic.key.openai")).toBe(KEY);
    expect(localStorage.getItem("aic.key.openai")).toBeNull();
    expect(getKey("openai")).toBe(KEY);
    expect(isRemembered("openai")).toBe(false);
  });

  it("test_set_key_remember_writes_local_storage_only", () => {
    setKey("openai", KEY, { remember: true });
    expect(localStorage.getItem("aic.key.openai")).toBe(KEY);
    expect(sessionStorage.getItem("aic.key.openai")).toBeNull();
    expect(getKey("openai")).toBe(KEY);
    expect(isRemembered("openai")).toBe(true);
  });

  it("test_set_key_switching_mode_removes_the_old_copy", () => {
    setKey("openai", KEY, { remember: true });
    setKey("openai", KEY, { remember: false });
    expect(localStorage.getItem("aic.key.openai")).toBeNull();
    expect(sessionStorage.getItem("aic.key.openai")).toBe(KEY);
  });

  it("test_keys_are_kept_per_provider", () => {
    setKey("openai", "k-one", { remember: false });
    setKey("anthropic", "k-two", { remember: false });
    expect(getKey("openai")).toBe("k-one");
    expect(getKey("anthropic")).toBe("k-two");
    expect(getKey("mistral")).toBeNull();
  });

  it("test_forget_key_removes_both_storages_for_that_provider_only", () => {
    setKey("openai", KEY, { remember: true });
    sessionStorage.setItem("aic.key.openai", KEY);
    setKey("anthropic", "k-two", { remember: false });
    forgetKey("openai");
    expect(getKey("openai")).toBeNull();
    expect(getKey("anthropic")).toBe("k-two");
  });

  it("test_forget_all_keys_removes_every_aic_key_prefix_entry_and_nothing_else", () => {
    setKey("openai", KEY, { remember: true });
    setKey("gemini", KEY, { remember: false });
    localStorage.setItem("aic.lang", "uk");
    forgetAllKeys();
    expect(getKey("openai")).toBeNull();
    expect(getKey("gemini")).toBeNull();
    expect(localStorage.getItem("aic.lang")).toBe("uk");
  });

  it("test_clear_all_data_removes_aic_key_entries_from_both_storages", async () => {
    setKey("openai", KEY, { remember: true });
    setKey("gemini", KEY, { remember: false });
    await clearAllData();
    expect(getKey("openai")).toBeNull();
    expect(getKey("gemini")).toBeNull();
    expect(localStorage.length + sessionStorage.length).toBe(0);
  });

  it("test_blocked_storage_does_not_throw", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(() => setKey("openai", KEY, { remember: false })).not.toThrow();
    expect(getKey("openai")).toBeNull();
    expect(() => forgetKey("openai")).not.toThrow();
    expect(() => forgetAllKeys()).not.toThrow();
  });
});
