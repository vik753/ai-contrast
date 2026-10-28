/**
 * The "Check replacements" step of one contract (S5b-T3, ADR 0015 point 3).
 *
 * Everything from the contract is plain text (React text nodes inside `<bdi>`): no HTML,
 * no Markdown, no links. Original values are shown here and nowhere else; this component
 * has no live region and logs nothing. Each clause text node maps to one piece of the
 * view, so a selection in the browser maps back to a block position.
 */
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ENTITY_CLASSES, type Span } from "../api/segment";
import { groupClauseWarnings } from "../upload/Preview";
import {
  canUnmask,
  countMaskable,
  maskAllEqual,
  maskSelection,
  occurrenceText,
  positionInPiece,
  trimSpan,
  unmaskEntity,
  unmaskOccurrence,
  viewOf,
  type Piece,
  type Review,
  type ViewClause,
} from "./masking";
import type { Phase } from "./usePseudoReviews";

const BREAK: Piece = { kind: "text", text: "\n", block: -1, start: 0 };

/** The pieces of a clause in display order: one DOM node each. */
function flat(clause: ViewClause): Piece[] {
  return clause.spans.flatMap((pieces, i) => (i === 0 ? pieces : [BREAK, ...pieces]));
}

/** The text piece and UTF-16 offset a DOM position stands for, or `null`. */
function resolve(
  root: HTMLElement,
  pieces: readonly Piece[],
  node: Node,
  offset: number,
  review: Review,
): { block: number; offset: number } | null {
  const path: number[] = [];
  let current: Node = node;
  while (current !== root) {
    const parent: ParentNode | null = current.parentNode;
    if (parent === null) {
      return null;
    }
    if (parent === root || (parent instanceof Element && parent.hasAttribute("data-pieces"))) {
      path.unshift(Array.from<Node>(parent.childNodes).indexOf(current));
    }
    current = parent;
  }
  let level: readonly Piece[] = pieces;
  for (const [depth, index] of path.entries()) {
    const piece = level[index];
    if (piece === undefined) {
      return null;
    }
    if (depth === path.length - 1) {
      if (piece.kind !== "text" || node.nodeType !== Node.TEXT_NODE) {
        return null;
      }
      return positionInPiece(review, piece, offset);
    }
    if (piece.kind !== "line") {
      return null;
    }
    level = piece.children;
  }
  return null;
}

interface Props {
  review: Review;
  phase: Phase;
  onChange: (review: Review) => void;
  onConfirm: () => void;
}

export function ReviewPanel({ review, phase, onChange, onConfirm }: Props) {
  const { t } = useTranslation();
  const rootRef = useRef<HTMLDivElement>(null);
  const baseId = useId();
  const view = viewOf(review);
  const [pending, setPending] = useState<Span | null>(null);
  const [choosing, setChoosing] = useState(false);
  const [cls, setCls] = useState<string>("ORG");
  const [refused, setRefused] = useState(false);
  const clauseViews = useMemo(
    () => new Map(view.clauses.map((item) => [item.clause.id, flat(item)])),
    [view],
  );

  // A selection inside one clause, in one block, is offered for masking.
  useEffect(() => {
    const read = (): void => {
      const selection = window.getSelection();
      const root = rootRef.current;
      if (
        selection === null ||
        root === null ||
        selection.rangeCount === 0 ||
        selection.isCollapsed
      ) {
        return;
      }
      const range = selection.getRangeAt(0);
      const clauseOf = (node: Node): HTMLElement | null =>
        (node instanceof Element ? node : node.parentElement)?.closest<HTMLElement>(
          "[data-clause-id]",
        ) ?? null;
      const element = clauseOf(range.startContainer);
      if (element === null || element !== clauseOf(range.endContainer) || !root.contains(element)) {
        return;
      }
      const pieces = clauseViews.get(element.dataset.clauseId ?? "");
      if (pieces === undefined) {
        return;
      }
      const from = resolve(element, pieces, range.startContainer, range.startOffset, review);
      const to = resolve(element, pieces, range.endContainer, range.endOffset, review);
      if (from?.block !== to?.block || from === null || to === null || to.offset <= from.offset) {
        return;
      }
      const span = trimSpan(review, [from.block, from.offset, to.offset]);
      if (span[2] > span[1]) {
        setPending(span);
        setChoosing(false);
        setRefused(false);
      }
    };
    document.addEventListener("selectionchange", read);
    return () => {
      document.removeEventListener("selectionchange", read);
    };
  }, [clauseViews, review]);

  const change = (next: Review): void => {
    setPending(null);
    setChoosing(false);
    onChange(next);
  };

  const mask = (all: boolean): void => {
    if (pending === null) {
      return;
    }
    const next = all ? maskAllEqual(review, pending, cls) : maskSelection(review, pending, cls);
    setRefused(next === review);
    if (next !== review) {
      change(next);
    } else {
      setPending(null);
      setChoosing(false);
    }
  };

  const warnings = useMemo(
    () => groupClauseWarnings(review.segmentation.warnings, review.segmentation.clauses),
    [review],
  );

  const renderPieces = (pieces: readonly Piece[]): ReactNode[] =>
    pieces.map((piece, i) => {
      switch (piece.kind) {
        case "text":
          return piece.text;
        case "neutralized":
          return (
            <span key={i} data-neutralized="" className="pseudo-neutralized">
              <bdi>{piece.text}</bdi>
            </span>
          );
        case "mark": {
          const entity = review.entities[piece.entity];
          const placeholder = view.placeholders[piece.entity] ?? "";
          return (
            <mark
              key={i}
              className="pseudo-mark"
              data-entity-id={entity?.id}
              data-length={piece.text.length}
              data-premasked={piece.premasked ? "" : undefined}
            >
              <bdi>{piece.text}</bdi>{" "}
              <span className="pseudo-mark__class">
                {entity === undefined ? "" : t(`pseudo.class.${entity.cls}`)}
              </span>{" "}
              <code className="pseudo-mark__placeholder">{placeholder}</code>
              {entity !== undefined && canUnmask(review, entity.id) && (
                <>
                  {" "}
                  <button
                    type="button"
                    className="button button--small button--quiet"
                    onClick={() => {
                      change(unmaskOccurrence(review, entity.id, piece.index));
                    }}
                  >
                    {t("pseudo.unmaskOne")}
                  </button>
                </>
              )}
              {piece.premasked && (
                <>
                  {" "}
                  <span className="pseudo-mark__note">{t("pseudo.premasked")}</span>
                </>
              )}
            </mark>
          );
        }
        case "line": {
          const drop = piece.action === "drop";
          const body = (
            <span data-requisites-action={piece.action} data-pieces="">
              {renderPieces(piece.children)}
            </span>
          );
          return (
            <span key={i} className="pseudo-line">
              {drop ? <s>{body}</s> : body}{" "}
              <small className="pseudo-line__note">
                {t(drop ? "pseudo.requisites.dropped" : "pseudo.requisites.kept")}
              </small>
            </span>
          );
        }
      }
    });

  const hasNeutralized = review.segmentation.neutralized.length > 0;

  return (
    <div ref={rootRef} className="pseudo-review" data-testid={`pseudo-review-${review.label}`}>
      <h5 className="pseudo-review__title">{t("pseudo.title")}</h5>
      <p className="pseudo-review__intro">{t("pseudo.intro")}</p>

      {(warnings.length > 0 || hasNeutralized) && (
        <ul className="preview-warnings">
          {warnings.map((group) => (
            <li key={group.key} className="preview-warning">
              <span>{t(group.key)}</span>
              {group.clauses.some((clause) => clause.number !== null) && (
                <span className="preview-warning__pages">
                  {" "}
                  {t("upload.preview.warningClauses", {
                    numbers: group.clauses
                      .map((clause) => clause.number)
                      .filter((number) => number !== null)
                      .join(", "),
                  })}
                </span>
              )}
            </li>
          ))}
          {hasNeutralized && (
            <li className="preview-warning">
              <span>{t("pseudo.neutralized.explanation")}</span>
            </li>
          )}
        </ul>
      )}

      <h6 className="pseudo-review__subtitle">{t("pseudo.clausesTitle")}</h6>
      <ol className="pseudo-clauses">
        {view.clauses.map((item) => (
          <li key={item.clause.id} className="pseudo-clause">
            {item.clause.number !== null && (
              <span className="pseudo-clause__number">
                <bdi>{item.clause.number}</bdi>
                {item.clause.sectionKind === "requisites" && (
                  <>
                    {" · "}
                    {t("upload.preview.requisites")}
                  </>
                )}
              </span>
            )}
            <p
              className="pseudo-clause__text preview-text"
              data-clause-id={item.clause.id}
              data-pieces=""
              onMouseUp={() => {
                document.dispatchEvent(new Event("selectionchange"));
              }}
            >
              {renderPieces(clauseViews.get(item.clause.id) ?? [])}
            </p>
          </li>
        ))}
      </ol>

      {pending !== null && !choosing && (
        <button
          type="button"
          className="button button--small"
          onMouseDown={(event) => {
            // Keep the selection while the button is pressed.
            event.preventDefault();
          }}
          onClick={() => {
            setChoosing(true);
          }}
        >
          {t("pseudo.maskSelection")}
        </button>
      )}
      {pending !== null && choosing && (
        <div className="pseudo-mask-form">
          <p>
            {t("pseudo.selected")}: <bdi>{occurrenceText(review, pending)}</bdi>
          </p>
          <label htmlFor={`${baseId}-class`}>{t("pseudo.maskClassLabel")}</label>{" "}
          <select
            id={`${baseId}-class`}
            value={cls}
            onChange={(event) => {
              setCls(event.currentTarget.value);
            }}
          >
            {ENTITY_CLASSES.map((value) => (
              <option key={value} value={value}>
                {t(`pseudo.class.${value}`)}
              </option>
            ))}
          </select>{" "}
          <button
            type="button"
            className="button button--small"
            onClick={() => {
              mask(false);
            }}
          >
            {t("pseudo.maskOnlyThis")}
          </button>{" "}
          <button
            type="button"
            className="button button--small"
            onClick={() => {
              mask(true);
            }}
          >
            {t("pseudo.maskAllEqual", { count: countMaskable(review, pending) })}
          </button>{" "}
          <button
            type="button"
            className="button button--small button--quiet"
            onClick={() => {
              setPending(null);
              setChoosing(false);
            }}
          >
            {t("pseudo.maskCancel")}
          </button>
        </div>
      )}
      {refused && <p className="pseudo-review__refused">{t("pseudo.maskRefused")}</p>}

      <h6 className="pseudo-review__subtitle">{t("pseudo.entitiesTitle")}</h6>
      <ul className="pseudo-entities">
        {review.entities.map((entity, index) => {
          const masked = entity.occurrences.some((occurrence) => occurrence.masked);
          const first = entity.occurrences[0];
          const placeholder = view.placeholders[index];
          const allowed = canUnmask(review, entity.id);
          const note = `${baseId}-cannot-${entity.id}`;
          return (
            <li
              key={entity.id}
              className="pseudo-entity"
              data-testid={`pseudo-entity-${entity.id}`}
            >
              <span className="pseudo-entity__class">{t(`pseudo.class.${entity.cls}`)}</span>{" "}
              {first !== undefined && <bdi>{occurrenceText(review, first.span)}</bdi>}{" "}
              {masked && placeholder !== null && placeholder !== undefined ? (
                <code>{placeholder}</code>
              ) : (
                !masked && <span>{t("pseudo.unmasked")}</span>
              )}{" "}
              {masked && (
                <button
                  type="button"
                  className="button button--small button--quiet"
                  disabled={!allowed}
                  aria-describedby={allowed ? undefined : note}
                  onClick={() => {
                    change(unmaskEntity(review, entity.id));
                  }}
                >
                  {t("pseudo.unmaskAll")}
                </button>
              )}
              {masked && !allowed && (
                <span id={note} className="pseudo-entity__note">
                  {t("pseudo.cannotUnmask")}
                </span>
              )}
            </li>
          );
        })}
      </ul>

      <div className="pseudo-review__actions">
        <button
          type="button"
          className="button"
          disabled={phase === "checking"}
          onClick={onConfirm}
        >
          {t("pseudo.everythingCorrect")}
        </button>
        {phase === "checking" && (
          <span className="pseudo-review__checking"> {t("pseudo.checking")}</span>
        )}
      </div>
    </div>
  );
}
