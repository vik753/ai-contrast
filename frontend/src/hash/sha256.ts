/** SHA-256 through Web Crypto (ADR 0013 point 8). No fallback implementation. */

export class HashUnavailableError extends Error {
  constructor() {
    super("Web Crypto is not available");
    this.name = "HashUnavailableError";
  }
}

/** Lower-case hex SHA-256 of bytes, or of a string encoded as UTF-8. */
export async function sha256Hex(data: ArrayBuffer | Uint8Array | string): Promise<string> {
  const subtle = (globalThis.crypto as Crypto | undefined)?.subtle;
  if (subtle === undefined) {
    throw new HashUnavailableError();
  }
  const bytes = typeof data === "string" ? new TextEncoder().encode(data) : data;
  const digest = await subtle.digest("SHA-256", bytes as BufferSource);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}
