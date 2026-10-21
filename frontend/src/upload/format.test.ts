// @vitest-environment node
/** Unit tests (frontend-dev) for `displaySize`. */
import { describe, expect, it } from "vitest";
import { displaySize, limitText } from "./format";

describe("displaySize", () => {
  it.each([
    [0, "en", { unit: "bytes", value: "0" }],
    [1023, "en", { unit: "bytes", value: "1,023" }],
    [1024, "en", { unit: "kb", value: "1" }],
    [1536, "en", { unit: "kb", value: "1.5" }],
    [10 * 1024 * 1024, "en", { unit: "mb", value: "10" }],
    [1536, "uk", { unit: "kb", value: "1,5" }],
    [1025, "en", { unit: "kb", value: "1.1" }],
    [1_048_575, "en", { unit: "mb", value: "1" }],
    [10_485_761, "en", { unit: "mb", value: "10.1" }],
    [-5, "en", { unit: "bytes", value: "0" }],
    [Number.NaN, "en", { unit: "bytes", value: "0" }],
  ] as const)("%d bytes in %s", (bytes, locale, expected) => {
    expect(displaySize(bytes, locale)).toEqual(expected);
  });
});

describe("limitText", () => {
  it.each([
    [10 * 1024 * 1024, "en", "10 megabytes"],
    [50 * 1024 * 1024, "ru", "50 мегабайт"],
  ] as const)("%d bytes in %s", (bytes, locale, expected) => {
    expect(limitText(bytes, locale)).toBe(expected);
  });
});
