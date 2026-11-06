/**
 * "Tag clauses" step (S8-T3, ADR 0018 point 8). One `POST /api/tag` per document, one after
 * another. Free mode: one Turnstile per analysis, then the analysis pass for the next document.
 * Everything from the server is rendered as plain text. Client tags only add; keyword, model and
 * check tags cannot be removed.
 */
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { getFrameOrigin } from "../provider/frameOrigin";
import { TurnstileFrame } from "../provider/TurnstileFrame";
import type { TopicConnection } from "../topics/TopicPanel";
import type { TopicSelection } from "../topics/types";
import { Chip, Layer2Badge, RiskText, useTk } from "./ClauseTags";
import { estimateTagging, modelPairOf } from "./estimate";
import type { MaskedDoc } from "./maskedDocsStore";
import { tagDocument, type TagReply } from "./tagApi";

const TOKEN_WAIT_MS = 30_000;
const MAX_CLIENT_PER_TOPIC = 120;
const MAX_NON_KEYWORD_PER_CLAUSE = 5;

export interface TaggingResult {
  label: string;
  digest: string;
  taggingVersion: string;
  signature: string;
  reply: TagReply;
  clientTags: Record<string, string[]>;
}

export interface TaggingStepProps {
  connection: TopicConnection & { checkModel?: string };
  turnstileToken?: string;
  documents: readonly MaskedDoc[];
  selection: TopicSelection;
  topicNames?: Readonly<Record<string, string>>;
  onResultsChange?: (results: readonly TaggingResult[]) => void;
}

type Status = "pending" | "running" | "done" | "failed";

function topicIds(s: TopicSelection): string[] {
  return [
    ...s.catalog.map((x) => x.topic_id),
    ...s.suggested.map((x) => x.topic_id),
    ...s.custom.map((x) => x.topic_id),
  ];
}

function domainSide(s: TopicSelection): { domain: string; side: string } {
  const c = s.catalog[0];
  if (c) return { domain: c.domain, side: c.side };
  const d = s.suggested[0] ?? s.custom[0];
  return { domain: d?.domain ?? "", side: d?.side ?? "" };
}

export function TaggingStep({
  connection,
  turnstileToken,
  documents,
  selection,
  topicNames,
  onResultsChange,
}: TaggingStepProps) {
  const tk = useTk();
  const titleId = useId();
  const [status, setStatus] = useState<Readonly<Record<string, Status>>>({});
  const [results, setResults] = useState<Readonly<Record<string, TaggingResult>>>({});
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [frameOn, setFrameOn] = useState(false);
  const mounted = useRef(true);
  const waiter = useRef<((token: string | null) => void) | null>(null);
  const controller = useRef<AbortController | null>(null);
  const free = connection.provider === "free";

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
      const w = waiter.current;
      waiter.current = null;
      w?.(null);
    };
  }, []);

  // A result belongs to the document text it was made for: another digest hides it.
  const shown = useMemo(
    () =>
      documents.flatMap((d) => {
        const r = results[d.label];
        return r?.digest === d.digest ? [r] : [];
      }),
    [documents, results],
  );
  const notify = useRef(onResultsChange);
  useEffect(() => {
    notify.current = onResultsChange;
  });
  useEffect(() => {
    notify.current?.(shown);
  }, [shown]);

  if (documents.length === 0) return null;

  const ids = topicIds(selection);
  const nameOf = (id: string): string => topicNames?.[id] ?? id;
  const pair = modelPairOf(connection);
  const estimate = estimateTagging(documents, ids.length);
  const showCheckDefault = !free && connection.checkModel === undefined;

  const acquireToken = (): Promise<string | null> => {
    try {
      getFrameOrigin();
    } catch {
      return Promise.resolve(null);
    }
    setFrameOn(true);
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        waiter.current = null;
        resolve(null);
      }, TOKEN_WAIT_MS);
      waiter.current = (token) => {
        clearTimeout(timer);
        resolve(token);
      };
    });
  };
  const onFrameToken = (token: string) => {
    const w = waiter.current;
    if (!w) return;
    waiter.current = null;
    setFrameOn(false);
    w(token);
  };
  const onFrameFailed = () => {
    const w = waiter.current;
    waiter.current = null;
    setFrameOn(false);
    w?.(null);
  };

  const setOne = (label: string, s: Status) => {
    setStatus((prev) => ({ ...prev, [label]: s }));
  };

  const start = async () => {
    if (running || ids.length === 0) return;
    const docs = [...documents];
    const { domain, side } = domainSide(selection);
    controller.current?.abort();
    const ctl = new AbortController();
    controller.current = ctl;
    setRunning(true);
    setError(null);
    setResults({});
    setStatus(Object.fromEntries(docs.map((d): [string, Status] => [d.label, "pending"])));
    // A new analysis never reuses an old pass.
    let pass: string | null = null;
    for (const doc of docs) {
      setOne(doc.label, "running");
      const req: Parameters<typeof tagDocument>[0] = {
        provider: connection.provider,
        domain,
        side,
        document: doc,
        topics: selection,
      };
      if (free) {
        if (pass !== null) req.analysisPass = pass;
        else if (turnstileToken !== undefined) req.turnstileToken = turnstileToken;
        else {
          const token = await acquireToken();
          if (!mounted.current) return;
          if (token === null) {
            setOne(doc.label, "failed");
            setError("turnstile_failed");
            break;
          }
          req.turnstileToken = token;
        }
      } else {
        if (connection.model !== undefined) req.model = connection.model;
        if (connection.checkModel !== undefined) req.checkModel = connection.checkModel;
        if (connection.baseUrl !== undefined) req.baseUrl = connection.baseUrl;
        if (connection.key !== undefined) req.key = connection.key;
      }
      const r = await tagDocument(req, ctl.signal);
      if (!mounted.current || ctl.signal.aborted) return;
      if (!r.ok) {
        if (r.code.startsWith("analysis_pass_")) pass = null;
        setOne(doc.label, "failed");
        setError(r.code);
        break;
      }
      if (r.analysisPass !== undefined) pass = r.analysisPass;
      if (r.data.digest !== doc.digest) {
        setOne(doc.label, "failed");
        setError("digest_mismatch");
        break;
      }
      const result: TaggingResult = {
        label: doc.label,
        digest: doc.digest,
        taggingVersion: r.data.tagging_version,
        signature: r.data.signature,
        reply: r.data,
        clientTags: {},
      };
      setResults((prev) => ({ ...prev, [doc.label]: result }));
      setOne(doc.label, "done");
    }
    if (mounted.current) setRunning(false);
  };

  const changeClient = (label: string, clauseId: string, next: string[]) => {
    setResults((prev) => {
      const r = prev[label];
      if (!r) return prev;
      const tags = Object.fromEntries(Object.entries(r.clientTags).filter(([k]) => k !== clauseId));
      if (next.length > 0) tags[clauseId] = next;
      return { ...prev, [label]: { ...r, clientTags: tags } };
    });
  };

  return (
    <section className="card" aria-labelledby={titleId}>
      <h2 id={titleId} className="card__title">
        {tk("tagging.title")}
      </h2>
      <p data-testid="tag-pair">
        {showCheckDefault
          ? tk("tagging.pairDefault", { cheap: pair.cheap })
          : tk("tagging.pair", { cheap: pair.cheap, strong: pair.strong })}
      </p>
      <p className="note" data-testid="tag-cost">
        {tk("tagging.cost", {
          calls: estimate.calls,
          checks: estimate.maxCheckCalls,
          tokens: estimate.inputTokens,
        })}
      </p>
      {ids.length === 0 ? <p className="note">{tk("tagging.noTopics")}</p> : null}
      {free && frameOn ? (
        <TurnstileFrame onToken={onFrameToken} onExpired={onFrameFailed} onError={onFrameFailed} />
      ) : null}
      <div className="provider__actions">
        <button
          type="button"
          className="button"
          disabled={running || ids.length === 0}
          onClick={() => void start()}
        >
          {tk("tagging.start")}
        </button>
      </div>
      {error !== null ? (
        <div role="alert" className="provider__error">
          <p>{tk(`tagging.error.${error}`)}</p>
        </div>
      ) : null}
      <ul aria-live="polite">
        {documents.map((d) => (
          <li key={d.label} data-testid={`tag-progress-${d.label}`}>
            <strong>{d.label}</strong>: {tk(`tagging.status.${status[d.label] ?? "pending"}`)}
          </li>
        ))}
      </ul>
      {documents.map((d) => {
        const r = shown.find((x) => x.label === d.label);
        return r ? (
          <DocumentResult
            key={d.label}
            doc={d}
            result={r}
            selectedIds={ids}
            nameOf={nameOf}
            onClient={(clauseId, next) => {
              changeClient(d.label, clauseId, next);
            }}
          />
        ) : null;
      })}
    </section>
  );
}

function DocumentResult({
  doc,
  result,
  selectedIds,
  nameOf,
  onClient,
}: {
  doc: MaskedDoc;
  result: TaggingResult;
  selectedIds: readonly string[];
  nameOf: (id: string) => string;
  onClient: (clauseId: string, next: string[]) => void;
}) {
  const tk = useTk();
  const { reply, clientTags } = result;
  const label = doc.label;
  const textOf = new Map(doc.clauses.map((c) => [c.id, c.text]));
  const clientCount = (topic: string): number =>
    Object.values(clientTags).filter((l) => l.includes(topic)).length;
  const offered = [...new Set(selectedIds)].filter(
    (id) => (reply.topics[id]?.keyword_clauses ?? 0) + clientCount(id) < MAX_CLIENT_PER_TOPIC,
  );

  return (
    <>
      <div data-testid={`tag-result-${label}`}>
        <h3>{label}</h3>
        {reply.model_tagging_incomplete ? (
          <div data-testid={`tag-incomplete-${label}`} className="note">
            {reply.incomplete_reasons.map((reason) => (
              <p key={reason}>{tk(`tagging.incomplete.${reason}`)}</p>
            ))}
          </div>
        ) : null}
        {reply.missing_topics.length > 0 ? (
          <div data-testid={`tag-missing-${label}`}>
            <p>{tk("tagging.missing.heading")}</p>
            <ul>
              {reply.missing_topics.map((id) => (
                <li key={id}>{nameOf(id)}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <ul>
          {Object.entries(reply.topics).map(([id, s]) => (
            <li key={id} data-testid={`tag-topic-${label}-${id}`}>
              <strong>{nameOf(id)}</strong>{" "}
              {tk("tagging.counts", { keyword: s.keyword_clauses, model: s.model_clauses })}
              {s.model_tags_dropped ? <p>{tk("tagging.flag.model_tags_dropped")}</p> : null}
              {s.not_analyzed !== null ? (
                <p>{tk(`tagging.flag.not_analyzed.${s.not_analyzed}`)}</p>
              ) : null}
            </li>
          ))}
        </ul>
        <ol className="tag-clauses">
          {doc.clauses.map((c) => {
            const tags = reply.tags[c.id] ?? [];
            const client = (clientTags[c.id] ?? []).filter(
              (id) => !tags.some((x) => x.topic_id === id),
            );
            const has = new Set([...tags.map((x) => x.topic_id), ...client]);
            const nonKeyword = tags.filter((x) => x.source !== "keyword").length + client.length;
            const capped = nonKeyword >= MAX_NON_KEYWORD_PER_CLAUSE;
            const options = offered.filter((id) => !has.has(id));
            const layer2 = reply.layer2[c.id];
            const classes = new Set([
              ...(layer2?.text ?? []).map((h) => h[2]),
              ...(layer2?.heading ?? []).map((h) => h[2]),
            ]);
            return (
              <li key={c.id} data-clause-id={c.id}>
                <p>{c.text}</p>
                <p>
                  {tags.map((x) => (
                    <Chip
                      key={`${x.topic_id}-${x.source}`}
                      topicId={x.topic_id}
                      name={nameOf(x.topic_id)}
                      source={x.source}
                    />
                  ))}
                  {client.map((id) => (
                    <Chip
                      key={`c-${id}`}
                      topicId={id}
                      name={nameOf(id)}
                      source="client"
                      onRemove={() => {
                        onClient(
                          c.id,
                          client.filter((x) => x !== id),
                        );
                      }}
                    />
                  ))}
                </p>
                {[...classes].map((cls) => (
                  <Layer2Badge key={cls} cls={cls} />
                ))}
                <AddTag
                  options={options}
                  capped={capped}
                  nameOf={nameOf}
                  onAdd={(id) => {
                    onClient(c.id, [...client, id]);
                  }}
                />
              </li>
            );
          })}
        </ol>
      </div>
      <div data-testid={`tag-other-${label}`}>
        <h4>{tk("tagging.other.heading")}</h4>
        <ul>
          {reply.other.map((id) => {
            const risk = reply.risk[id];
            return (
              <li key={id} data-clause-id={id}>
                <p>
                  <RiskText text={textOf.get(id) ?? ""} spans={risk ?? []} />
                </p>
                {risk && risk.length > 0 ? (
                  <p className="note">{tk("tagging.risk.label")}</p>
                ) : null}
              </li>
            );
          })}
        </ul>
      </div>
    </>
  );
}

function AddTag({
  options,
  capped,
  nameOf,
  onAdd,
}: {
  options: readonly string[];
  capped: boolean;
  nameOf: (id: string) => string;
  onAdd: (id: string) => void;
}) {
  const tk = useTk();
  const id = useId();
  const [value, setValue] = useState("");
  const current = options.includes(value) ? value : "";
  return (
    <p>
      <label htmlFor={id}>{tk("tagging.add.label")}</label>{" "}
      <select
        id={id}
        value={current}
        disabled={capped}
        onChange={(e) => {
          setValue(e.target.value);
        }}
      >
        <option value="" />
        {options.map((o) => (
          <option key={o} value={o}>
            {nameOf(o)}
          </option>
        ))}
      </select>{" "}
      <button
        type="button"
        className="button button--quiet button--small"
        disabled={capped || current === ""}
        onClick={() => {
          onAdd(current);
          setValue("");
        }}
      >
        {tk("tagging.add.button")}
      </button>
      {capped ? <span className="note"> {tk("tagging.add.clauseCap")}</span> : null}
    </p>
  );
}
