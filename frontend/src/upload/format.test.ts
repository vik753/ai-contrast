// @vitest-environment node
/** Unit tests (frontend-dev) for `displaySize`. */
import { describe, expect, it } from "vitest";
import { displaySize } from "./format";

describe("displaySize", () => {
  it.each([
    [0, "en", { unit: "bytes", value: "0" }],
    [1023, "en", { unit: "bytes", value: "1,023" }],
    [1024, "en", { unit: "kb", value: "1" }],
    [1536, "en", { unit: "kb", value: "1.5" }],
    [10 * 1024 * 1024, "en", { unit: "mb", value: "10" }],
    [1536, "uk", { unit: "kb", value: "1,5" }],
    [-5, "en", { unit: "bytes", value: "0" }],
    [Number.NaN, "en", { unit: "bytes", value: "0" }],
  ] as const)("%d bytes in %s", (bytes, locale, expected) => {
    expect(displaySize(bytes, locale)).toEqual(expected);
  });
});
