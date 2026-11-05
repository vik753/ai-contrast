/** S7-T3 types. Wire names stay snake_case (they are the backend JSON). */

export const MAX_OWN_TOPICS = 10;

export type Lang = "en" | "uk" | "ru";
export type Localized = Readonly<Record<Lang, string>>;

export const ATTRIBUTE_TYPES = [
  "amount",
  "percentage",
  "duration",
  "enum",
  "categories",
  "text",
] as const;
export type AttributeType = (typeof ATTRIBUTE_TYPES)[number];

export interface AttributeDefinition {
  id: string;
  label: string;
  type: AttributeType;
  units: string[];
  direction: string;
  order: string[];
  values: string[];
  direction_source: "catalog" | "client";
}

export interface TopicDefinition {
  origin: "catalog" | "suggested" | "custom";
  domain: string | null;
  topic_id: string;
  title: string;
  description: string;
  side: string;
  attributes: AttributeDefinition[];
  synonyms_en: string[];
  synonyms_uk: string[];
  synonyms_ru: string[];
}

export interface CatalogAttribute {
  id: string;
  labels: Localized;
  type: AttributeType;
  units?: string[];
  values?: { id: string; labels: Localized }[];
  directions: Record<string, string | string[]>;
}

export interface CatalogTopic {
  id: string;
  names: Localized;
  descriptions: Localized;
  synonyms: Record<Lang, string[]>;
  attributes: CatalogAttribute[];
}

export interface CatalogDomain {
  id: string;
  names: Localized;
  sides: { id: string; names: Localized }[];
  topics: CatalogTopic[];
}

/** Body of `GET /api/topics/catalog`. */
export interface Catalog {
  catalog_version: string;
  domains: CatalogDomain[];
}

export interface CatalogRef {
  domain: string;
  topic_id: string;
  side: string;
  lang: string;
  catalog_version: string;
}

export interface TopicSelection {
  catalog: CatalogRef[];
  suggested: TopicDefinition[];
  custom: TopicDefinition[];
}

/** Direction options a client may choose, by attribute type. */
export function directionOptions(type: AttributeType): readonly string[] {
  switch (type) {
    case "amount":
    case "percentage":
    case "duration":
      return ["none", "lower_better", "higher_better"];
    case "categories":
      return ["none", "more_better", "fewer_better"];
    default:
      return ["none"];
  }
}
