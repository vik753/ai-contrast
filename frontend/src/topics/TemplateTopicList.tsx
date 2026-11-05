import { useId } from "react";
import { useT } from "./useT";
import type { CatalogAttribute, CatalogDomain, Lang } from "./types";

interface Props {
  domain: CatalogDomain;
  side: string;
  lang: Lang;
  off: ReadonlySet<string>;
  onToggle: (topicId: string) => void;
}

type DirectionKey =
  "none" | "lower_better" | "higher_better" | "more_better" | "fewer_better" | "ordered";
const DIRECTIONS: readonly string[] = [
  "none",
  "lower_better",
  "higher_better",
  "more_better",
  "fewer_better",
];

function directionKey(attribute: CatalogAttribute, side: string): DirectionKey {
  const d = attribute.directions[side];
  if (Array.isArray(d)) return "ordered";
  return d !== undefined && DIRECTIONS.includes(d) ? (d as DirectionKey) : "none";
}

export function TemplateTopicList({ domain, side, lang, off, onToggle }: Props) {
  const { t } = useT();
  const heading = useId();
  return (
    <section aria-labelledby={heading}>
      <h3 id={heading}>{t("topics.templates.heading")}</h3>
      <ul>
        {domain.topics.map((topic) => {
          const box = `${heading}-${topic.id}`;
          return (
            <li key={topic.id}>
              <input
                id={box}
                type="checkbox"
                checked={!off.has(topic.id)}
                onChange={() => {
                  onToggle(topic.id);
                }}
              />{" "}
              <label htmlFor={box}>{topic.names[lang]}</label>
              <ul>
                {topic.attributes.map((a) => (
                  <li key={a.id}>
                    {a.labels[lang]} ({t(`topics.direction.${directionKey(a, side)}`)})
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
