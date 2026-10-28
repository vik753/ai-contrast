// @vitest-environment node
/**
 * S4-T1 AC1 — `sha256Hex` (src/hash/sha256.ts).
 * Fails until the module exists.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { HashUnavailableError, sha256Hex } from "./sha256";

const EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
const ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("sha256Hex", () => {
  it("test_sha256Hex_string_abc_matches_known_vector", async () => {
    expect(await sha256Hex("abc")).toBe(ABC);
  });

  it("test_sha256Hex_empty_string_matches_known_vector", async () => {
    expect(await sha256Hex("")).toBe(EMPTY);
  });

  it("test_sha256Hex_result_is_64_lower_case_hex_characters", async () => {
    expect(await sha256Hex("Contract")).toMatch(/^[0-9a-f]{64}$/);
  });

  it("test_sha256Hex_uint8array_matches_string", async () => {
    expect(await sha256Hex(new TextEncoder().encode("abc"))).toBe(ABC);
  });

  it("test_sha256Hex_arraybuffer_matches_string", async () => {
    const bytes = new TextEncoder().encode("abc");
    expect(await sha256Hex(bytes.buffer.slice(0))).toBe(ABC);
  });

  it("test_sha256Hex_string_is_utf8_encoded", async () => {
    expect(await sha256Hex("é")).toBe(await sha256Hex(new Uint8Array([0xc3, 0xa9])));
  });

  it("test_sha256Hex_uint8array_view_hashes_only_the_view", async () => {
    const whole = new TextEncoder().encode("xxabcyy");
    expect(await sha256Hex(whole.subarray(2, 5))).toBe(ABC);
  });

  it("test_sha256Hex_missing_subtle_rejects_with_hash_unavailable_error", async () => {
    vi.stubGlobal("crypto", {});
    await expect(sha256Hex("abc")).rejects.toBeInstanceOf(HashUnavailableError);
  });

  it("test_sha256Hex_missing_crypto_rejects_with_hash_unavailable_error", async () => {
    vi.stubGlobal("crypto", undefined);
    await expect(sha256Hex("abc")).rejects.toBeInstanceOf(HashUnavailableError);
  });

  it("test_HashUnavailableError_is_an_error", () => {
    expect(new HashUnavailableError()).toBeInstanceOf(Error);
  });
});
