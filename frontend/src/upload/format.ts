/** File size for display: a localized number and a unit key (1024-based). */
export interface DisplaySize {
  unit: "bytes" | "kb" | "mb";
  value: string;
}

const KIB = 1024;
const MIB = 1024 * 1024;

export function displaySize(bytes: number, locale: string): DisplaySize {
  const safe = Number.isFinite(bytes) && bytes > 0 ? bytes : 0;
  const format = (value: number, digits: number): string =>
    new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value);
  if (safe < KIB) {
    return { unit: "bytes", value: format(safe, 0) };
  }
  if (safe < MIB) {
    return { unit: "kb", value: format(safe / KIB, 1) };
  }
  return { unit: "mb", value: format(safe / MIB, 1) };
}
