/** Plain-text pieces of the tagging result. Clause text and ids are never rendered as HTML. */
import type { ReactNode } from "react";
import { useT } from "../topics/useT";
import type { Layer2Class, Span, TagSource } from "./tagApi";

export type ChipSource = TagSource | "client";

const ICONS: Record<ChipSource, string> = {
  keyword: "#",
  model: "*",
  check: "+",
  client: "@",
};

/** Typed-key bridge: the keys are built from closed enums. */
export function useTk() {
  const { t } = useT();
  // Keys are built from closed enums and are checked by the locale tests, so the typed-key
  // check of i18next cannot help here: the cast is deliberate and the options type is plain.
  return (key: string, options?: Record<string, string | number>): string =>
    t(key as "tagging.title", (options ?? {}) as never) as unknown as string;
}

export function Chip({
  topicId,
  name,
  source,
  onRemove,
}: {
  topicId: string;
  name: string;
  source: ChipSource;
  onRemove?: () => void;
}) {
  const tk = useTk();
  return (
    <span className={`tag-chip tag-chip--${source}`} data-topic-id={topicId} data-source={source}>
      <span data-source-icon={source} aria-hidden="true">
        {ICONS[source]}
      </span>{" "}
      <span>{name}</span>{" "}
      <span className="tag-chip__source">({tk(`tagging.source.${source}`)})</span>
      {onRemove ? (
        <>
          {" "}
          <button
            type="button"
            className="button button--quiet button--small"
            aria-label={tk("tagging.removeTag", { topic: name })}
            onClick={onRemove}
          >
            <span aria-hidden="true">x</span>
          </button>
        </>
      ) : null}
    </span>
  );
}

/** The text of `spans` (code point offsets) with the spans in `<mark data-risk>`. */
export function RiskText({ text, spans }: { text: string; spans: readonly Span[] }) {
  const chars = Array.from(text);
  const sorted = [...spans].sort((a, b) => a[0] - b[0]);
  const nodes: ReactNode[] = [];
  let at = 0;
  for (const [s, e] of sorted) {
    const start = Math.max(s, at);
    const end = Math.min(e, chars.length);
    if (end <= start) continue;
    if (start > at)
      nodes.push(<span key={`t${String(at)}`}>{chars.slice(at, start).join("")}</span>);
    nodes.push(
      <mark key={`m${String(start)}`} data-risk="">
        {chars.slice(start, end).join("")}
      </mark>,
    );
    at = end;
  }
  if (at < chars.length) nodes.push(<span key={`t${String(at)}`}>{chars.slice(at).join("")}</span>);
  return <>{nodes}</>;
}

export function Layer2Badge({ cls }: { cls: Layer2Class }) {
  const tk = useTk();
  return (
    <span className="tag-layer2" data-layer2={cls}>
      <span aria-hidden="true">! </span>
      {tk(`tagging.layer2.${cls}`)}
    </span>
  );
}
