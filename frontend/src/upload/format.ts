/**
 * File size for display: a localized number and a unit key.
 * Units are 1024-based: 1 KB = 1024 bytes, 1 MB = 1024² bytes.
 * Values round up to one decimal, so a size is never shown below its real
 * value (10,485,761 bytes → "10.1 MB", just above the 10 MB limit).
 */
export interface DisplaySize {
  unit: "bytes" | "kb" | "mb";
  value: string;
}

const KIB = 1024;
const MIB = 1024 * 1024;

/** Tenths of `unit`, rounded up. `bytes * 10 / 2^n` is exact in binary. */
function ceilTenths(bytes: number, unit: number): number {
  return Math.ceil((bytes * 10) / unit) / 10;
}

export function displaySize(bytes: number, locale: string): DisplaySize {
  const safe = Number.isFinite(bytes) && bytes > 0 ? Math.ceil(bytes) : 0;
  const format = (value: number, digits: number): string =>
    new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value);
  if (safe < KIB) {
    return { unit: "bytes", value: format(safe, 0) };
  }
  const kb = ceilTenths(safe, KIB);
  // Rounding up may reach 1024 KB: show it as MB instead ("1 MB", not "1,024 KB").
  if (kb < KIB) {
    return { unit: "kb", value: format(kb, 1) };
  }
  return { unit: "mb", value: format(ceilTenths(safe, MIB), 1) };
}

/**
 * A limit in megabytes with the unit as a word ("10 megabytes"), localized
 * with plural forms by `Intl`. Used in messages, so a limit never reads
 * like a file size. "Megabyte" means 1024² bytes here, as everywhere in the UI.
 */
export function limitText(bytes: number, locale: string): string {
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit: "megabyte",
    unitDisplay: "long",
    maximumFractionDigits: 1,
  }).format(bytes / MIB);
}
