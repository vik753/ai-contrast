/** Origin of the Turnstile frame page (ADR 0016 point 7). A build setting. */
const DEV_FALLBACK = "http://localhost:5174";

/** Throws when production has no valid `VITE_TURNSTILE_FRAME_ORIGIN`. */
export function getFrameOrigin(): string {
  const raw = import.meta.env.VITE_TURNSTILE_FRAME_ORIGIN ?? "";
  if (raw === "") {
    if (import.meta.env.DEV) return DEV_FALLBACK;
    throw new Error("frame origin is not configured");
  }
  let origin: string;
  try {
    origin = new URL(raw).origin;
  } catch {
    throw new Error("frame origin is invalid");
  }
  if (origin !== raw) throw new Error("frame origin is invalid");
  return origin;
}
