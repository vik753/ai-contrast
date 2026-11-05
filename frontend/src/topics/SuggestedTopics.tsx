import { useT } from "./useT";
import type { Suggestion } from "./api";

interface Props {
  suggestions: readonly Suggestion[];
  dropped: number;
  onAccept: (s: Suggestion) => void;
}

/** Model strings are rendered as plain text nodes only. */
export function SuggestedTopics({ suggestions, dropped, onAccept }: Props) {
  const { t } = useT();
  return (
    <div>
      {dropped > 0 ? (
        <p className="note">{t("topics.suggest.dropped", { count: dropped })}</p>
      ) : null}
      {suggestions.length > 0 ? (
        <ul>
          {suggestions.map((s) => (
            <li key={s.id}>
              <strong>{s.name}</strong> <span>{s.description}</span>{" "}
              <button
                type="button"
                className="button button--quiet button--small"
                onClick={() => {
                  onAccept(s);
                }}
              >
                {t("topics.suggest.accept")}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
