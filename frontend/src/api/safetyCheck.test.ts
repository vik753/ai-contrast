/**
 * S5b-T3 AC 4: client of `POST /api/safety-check` (ADR 0015 point 4, TASKS S5b-T2 AC 2).
 *
 * ASSUMED API of `src/api/safetyCheck.ts`:
 *   checkSafety({ label, detectorVersion, clauses: [{id, text}], acknowledgedUnmasked },
 *               { fetchImpl? }) => Promise<
 *     { ok: true; digest: string; detectorVersion: string }
 *   | { ok: false; code: string; spans?: [string, number, number][] }>
 * Never throws. Error bodies are mapped by allowlisted code only.
 */
import { describe, expect, it, vi } from "vitest";
import { jsonResponse } from "../test/upload-fakes";
import * as safety from "./safetyCheck";

const DOC = {
  label: "A",
  detectorVersion: "det-1",
  clauses: [
    { id: "c1", text: "Seller [A.ORG_1] pays." },
    { id: "c2", text: "Tax [A.TAX_ID_1]." },
  ],
  acknowledgedUnmasked: [["c1", 3, 9]] as [string, number, number][],
};
const DIGEST = "a".repeat(64);

function run(status: number, reply: unknown) {
  const fetchImpl = vi.fn(() => Promise.resolve(jsonResponse(status, reply)));
  return { fetchImpl, result: safety.checkSafety(DOC, { fetchImpl: fetchImpl as never }) };
}

describe("request", () => {
  it("test_check_safety_posts_json_to_the_safety_endpoint", async () => {
    const { fetchImpl, result } = run(200, { ok: true, detector_version: "det-1", digest: DIGEST });
    await result;
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/safety-check");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
  });

  it("test_check_safety_body_has_exactly_the_documented_keys", async () => {
    const { fetchImpl, result } = run(200, { ok: true, detector_version: "det-1", digest: DIGEST });
    await result;
    const init = (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(JSON.parse(String(init.body))).toEqual({
      label: "A",
      detector_version: "det-1",
      clauses: DOC.clauses,
      acknowledged_unmasked: [["c1", 3, 9]],
    });
  });

  it("test_check_safety_sends_no_credentials_or_provider_key", async () => {
    const { fetchImpl, result } = run(200, { ok: true, detector_version: "det-1", digest: DIGEST });
    await result;
    const init = (fetchImpl.mock.calls[0] as unknown as [string, RequestInit])[1];
    expect(init.credentials === undefined || init.credentials === "omit").toBe(true);
    expect(new Headers(init.headers).has("X-Provider-Key")).toBe(false);
  });
});

describe("answers", () => {
  it("test_ok_answer_is_accepted", async () => {
    const { result } = run(200, { ok: true, detector_version: "det-1", digest: DIGEST });
    expect(await result).toMatchObject({ ok: true, digest: DIGEST });
  });

  it("test_ok_answer_with_bad_digest_is_invalid_response", async () => {
    const { result } = run(200, { ok: true, detector_version: "det-1", digest: "xyz" });
    expect(await result).toEqual({ ok: false, code: "invalid_response" });
  });

  it("test_ok_answer_with_extra_key_is_invalid_response", async () => {
    const { result } = run(200, { ok: true, detector_version: "det-1", digest: DIGEST, text: "x" });
    expect(await result).toEqual({ ok: false, code: "invalid_response" });
  });

  it("test_ok_false_in_a_200_body_is_invalid_response", async () => {
    const { result } = run(200, { ok: false, detector_version: "det-1", digest: DIGEST });
    expect(await result).toEqual({ ok: false, code: "invalid_response" });
  });

  it("test_unmasked_identifier_returns_spans", async () => {
    const { result } = run(422, {
      error: "unmasked_identifier",
      spans: [
        ["c1", 3, 9],
        ["c2", 0, 2],
      ],
    });
    expect(await result).toEqual({
      ok: false,
      code: "unmasked_identifier",
      spans: [
        ["c1", 3, 9],
        ["c2", 0, 2],
      ],
    });
  });

  it.each([
    [{ error: "unmasked_identifier" }],
    [{ error: "unmasked_identifier", spans: [["c1", "a", 2]] }],
    [{ error: "unmasked_identifier", spans: [["c1", 5, 2]] }],
    [{ error: "unmasked_identifier", spans: "c1" }],
    [{ error: "unmasked_identifier", spans: [["c1", 1, 2]], text: "John" }],
  ])("test_unmasked_identifier_with_malformed_spans_is_invalid_response_%#", async (reply) => {
    const { result } = run(422, reply);
    expect(await result).toEqual({ ok: false, code: "invalid_response" });
  });

  it("test_version_mismatch_409_is_mapped", async () => {
    const { result } = run(409, { error: "detector_version_mismatch" });
    expect(await result).toEqual({ ok: false, code: "detector_version_mismatch" });
  });

  it.each(["input_not_clean", "invalid_placeholder", "invalid_request"])(
    "test_422_%s_is_mapped",
    async (code) => {
      const { result } = run(422, { error: code });
      expect(await result).toEqual({ ok: false, code });
    },
  );

  it.each([
    [413, "request_too_large"],
    [503, "busy"],
    [504, "safety_timeout"],
  ])("test_transport_status_%i_maps_to_%s", async (status, code) => {
    const { result } = run(status, { error: code });
    expect(await result).toMatchObject({ ok: false, code });
  });

  it("test_unknown_error_code_never_reaches_the_ui", async () => {
    const { result } = run(422, { error: "John Smith is unmasked" });
    const r = await result;
    expect(r.ok).toBe(false);
    expect(JSON.stringify(r)).not.toContain("John");
  });

  it("test_network_failure_is_a_network_error", async () => {
    const r = await safety.checkSafety(DOC, {
      fetchImpl: (() => Promise.reject(new TypeError("down"))) as never,
    });
    expect(r).toMatchObject({ ok: false, code: "network_error" });
  });
});
