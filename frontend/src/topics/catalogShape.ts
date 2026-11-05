/** Shape guards for the catalog (server reply or bundled file). Server text is untrusted. */
import { ATTRIBUTE_TYPES, type Catalog, type CatalogDomain } from "./types";

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isStrArray = (v: unknown): v is string[] => Array.isArray(v) && v.every(isStr);
const isLocalized = (v: unknown): boolean =>
  isRecord(v) && isStr(v.en) && isStr(v.uk) && isStr(v.ru);

function isAttribute(v: unknown): boolean {
  if (!isRecord(v)) return false;
  if (!isStr(v.id) || !isLocalized(v.labels)) return false;
  if (!isStr(v.type) || !(ATTRIBUTE_TYPES as readonly string[]).includes(v.type)) return false;
  if (v.units !== undefined && !isStrArray(v.units)) return false;
  if (
    v.values !== undefined &&
    !(
      Array.isArray(v.values) &&
      v.values.every((x) => isRecord(x) && isStr(x.id) && isLocalized(x.labels))
    )
  )
    return false;
  return (
    isRecord(v.directions) && Object.values(v.directions).every((d) => isStr(d) || isStrArray(d))
  );
}

function isTopic(v: unknown): boolean {
  if (!isRecord(v) || !isStr(v.id)) return false;
  if (!isLocalized(v.names) || !isLocalized(v.descriptions)) return false;
  const s = v.synonyms;
  if (!isRecord(s) || !isStrArray(s.en) || !isStrArray(s.uk) || !isStrArray(s.ru)) return false;
  return Array.isArray(v.attributes) && v.attributes.every(isAttribute);
}

export function isCatalogDomain(v: unknown): v is CatalogDomain {
  if (!isRecord(v) || !isStr(v.id) || !isLocalized(v.names)) return false;
  if (
    !Array.isArray(v.sides) ||
    !v.sides.every((x) => isRecord(x) && isStr(x.id) && isLocalized(x.names))
  )
    return false;
  return Array.isArray(v.topics) && v.topics.every(isTopic);
}

export function isCatalog(v: unknown): v is Catalog {
  return (
    isRecord(v) &&
    isStr(v.catalog_version) &&
    Array.isArray(v.domains) &&
    v.domains.every(isCatalogDomain)
  );
}
