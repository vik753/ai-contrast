/**
 * Text normalization before hashing (ADR 0013 point 8): NFC; CRLF and CR to LF;
 * tabs and runs of spaces to one space; spaces at line ends removed; three or
 * more line breaks to two; leading and trailing white space removed.
 */
export function normalizeForHash(text: string): string {
  return text
    .normalize("NFC")
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+/g, " ")
    .replace(/ ?\n ?/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
