import { useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { SafetyDocument } from "../api/safetyCheck";
import {
  fetchCatalog,
  proposeAttributes,
  suggestTopics,
  type CommonRequest,
  type Suggestion,
  type TopicResult,
} from "./api";
import { bundledCatalog } from "./bundled";
import { DomainSelect } from "./DomainSelect";
import { OwnTopicEditor, type EditorState } from "./OwnTopicEditor";
import { SideSelect } from "./SideSelect";
import { SuggestedTopics } from "./SuggestedTopics";
import { TemplateTopicList } from "./TemplateTopicList";
import { topicStore } from "./topicStore";
import { MAX_IMPORT_BYTES, exportTopics, importTopics, type ImportResult } from "./transfer";
import { MAX_OWN_TOPICS, type Catalog, type TopicDefinition, type TopicSelection } from "./types";
import { useT } from "./useT";

export interface TopicConnection {
  provider: string;
  model?: string;
  baseUrl?: string;
  key?: string;
}

export interface TopicPanelProps {
  connection: TopicConnection;
  turnstileToken?: string;
  documents: readonly SafetyDocument[];
  onSelectionChange?: (selection: TopicSelection) => void;
}

type Notice =
  | { kind: "api"; code: string; field?: string; spans?: [number, number][]; text?: string }
  | { kind: "import"; code: string };

const EMPTY_EDITOR: EditorState = {
  name: "",
  description: "",
  suggestedId: null,
  attributes: null,
};

/** The text of `spans` (code point offsets from the server) as plain-text segments. */
function Highlighted({ text, spans }: { text: string; spans: [number, number][] }) {
  const chars = Array.from(text);
  const sorted = [...spans].sort((a, b) => a[0] - b[0]);
  const parts: { text: string; mark: boolean }[] = [];
  let at = 0;
  for (const [s, e] of sorted) {
    const start = Math.max(s, at);
    const end = Math.min(e, chars.length);
    if (end <= start) continue;
    if (start > at) parts.push({ text: chars.slice(at, start).join(""), mark: false });
    parts.push({ text: chars.slice(start, end).join(""), mark: true });
    at = end;
  }
  if (at < chars.length) parts.push({ text: chars.slice(at).join(""), mark: false });
  const nodes = parts.map((part, i) => {
    if (part.mark) return <mark key={i}>{part.text}</mark>;
    return <span key={i}>{part.text}</span>;
  });
  return <p>{nodes}</p>;
}

function readText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      resolve(typeof reader.result === "string" ? reader.result : "");
    };
    reader.onerror = () => {
      reject(new Error("read"));
    };
    reader.readAsText(file);
  });
}

function download(text: string): void {
  try {
    const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "aicontrast-topics.json";
    a.click();
    URL.revokeObjectURL(url);
  } catch {
    // No download available in this browser.
  }
}

/** Topic panel (ADR 0017 point 7): templates, suggestions, own topics. */
export function TopicPanel({
  connection,
  turnstileToken,
  documents,
  onSelectionChange,
}: TopicPanelProps) {
  const { t, lang } = useT();
  const titleId = useId();
  const importId = useId();
  const persistId = useId();
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [offline, setOffline] = useState(false);
  const [domainId, setDomainId] = useState("");
  const [sideId, setSideId] = useState("");
  const [off, setOff] = useState<ReadonlySet<string>>(new Set());
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [dropped, setDropped] = useState(0);
  const [editor, setEditor] = useState<EditorState>(EMPTY_EDITOR);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);
  const pass = useRef<string | null>(null);
  const mounted = useRef(true);
  const own = useSyncExternalStore(topicStore.subscribe, topicStore.getTopics);
  const persisted = useSyncExternalStore(topicStore.subscribe, topicStore.isPersisted);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    void fetchCatalog(controller.signal).then((r) => {
      if (controller.signal.aborted) return;
      if (r.ok) {
        setCatalog(r.data);
        return;
      }
      const fallback = bundledCatalog();
      if (fallback) {
        setCatalog(fallback);
        setOffline(true);
      } else {
        setNotice({ kind: "api", code: r.code });
      }
    });
    return () => {
      mounted.current = false;
      controller.abort();
    };
  }, []);

  const domain = catalog?.domains.find((d) => d.id === domainId) ?? null;

  const selection = useMemo<TopicSelection>(
    () => ({
      catalog:
        catalog && domain
          ? domain.topics
              .filter((x) => !off.has(x.id))
              .map((x) => ({
                domain: domain.id,
                topic_id: x.id,
                side: sideId,
                lang,
                catalog_version: catalog.catalog_version,
              }))
          : [],
      suggested: own.filter((x) => x.origin === "suggested"),
      custom: own.filter((x) => x.origin === "custom"),
    }),
    [catalog, domain, off, sideId, lang, own],
  );
  const notify = useRef(onSelectionChange);
  useEffect(() => {
    notify.current = onSelectionChange;
  });
  useEffect(() => {
    notify.current?.(selection);
  }, [selection]);

  const onDomain = (id: string) => {
    setDomainId(id);
    setOff(new Set());
    setSuggestions([]);
    setDropped(0);
    const d = catalog?.domains.find((x) => x.id === id);
    setSideId(d?.sides[0]?.id ?? "");
  };

  const common = (): CommonRequest => {
    const req: CommonRequest = { provider: connection.provider };
    if (connection.model !== undefined) req.model = connection.model;
    if (connection.baseUrl !== undefined) req.baseUrl = connection.baseUrl;
    if (connection.provider === "free") {
      if (pass.current !== null) req.freePass = pass.current;
      else if (turnstileToken !== undefined) req.turnstileToken = turnstileToken;
    } else if (connection.key !== undefined) {
      req.key = connection.key;
    }
    return req;
  };

  /** Keeps the free pass in step with the reply and shows a failure. */
  const settle = <T,>(
    r: TopicResult<T>,
    text?: string,
  ): r is Extract<TopicResult<T>, { ok: true }> => {
    if (r.ok) {
      if (r.freePass !== undefined) pass.current = r.freePass;
      return true;
    }
    if (r.code.startsWith("free_pass_")) pass.current = null;
    const n: Notice = { kind: "api", code: r.code };
    if (r.field !== undefined) n.field = r.field;
    if (r.spans !== undefined) n.spans = r.spans;
    if (text !== undefined) n.text = text;
    setNotice(n);
    return false;
  };

  const uniqueId = (prefix: string): string => {
    const used = new Set(topicStore.getTopics().map((x) => x.topic_id));
    for (let n = 1; ; n++) {
      if (!used.has(`${prefix}_${String(n)}`)) return `${prefix}_${String(n)}`;
    }
  };

  const draft = (): TopicDefinition => {
    const suggested = editor.suggestedId !== null && editor.description === "";
    return {
      origin: suggested ? "suggested" : "custom",
      domain: domainId === "" ? null : domainId,
      topic_id: uniqueId(suggested ? "suggested" : "custom"),
      title: editor.name.trim(),
      description: editor.description.trim(),
      side: sideId,
      attributes: editor.attributes ?? [],
      synonyms_en: [],
      synonyms_uk: [],
      synonyms_ru: [],
    };
  };

  const onSuggest = async () => {
    if (domainId === "" || busy) return;
    setBusy(true);
    setNotice(null);
    const all: Suggestion[] = [];
    let skipped = 0;
    for (const document of documents) {
      const r = await suggestTopics({ ...common(), domain: domainId, side: sideId, document });
      if (!mounted.current) return;
      if (!settle(r)) break;
      skipped += r.data.dropped;
      for (const s of r.data.suggestions) {
        all.push({ ...s, id: `suggested_${String(all.length + 1)}` });
      }
    }
    if (!mounted.current) return;
    setSuggestions(all);
    setDropped(skipped);
    setBusy(false);
  };

  const onPropose = async () => {
    if (domainId === "" || busy) return;
    const topic = { ...draft(), attributes: [] };
    setBusy(true);
    setNotice(null);
    const r = await proposeAttributes({ ...common(), topic });
    if (!mounted.current) return;
    setBusy(false);
    const fieldText = (field: string | undefined) =>
      field === "title" ? topic.title : field === "description" ? topic.description : undefined;
    if (!settle(r, !r.ok ? fieldText(r.field) : undefined)) return;
    setEditor((e) => ({
      ...e,
      attributes: r.data.attributes.map((a) => ({
        ...a,
        direction: "none",
        order: [],
        direction_source: "client" as const,
      })),
    }));
  };

  const onConfirm = () => {
    if (own.length >= MAX_OWN_TOPICS) return;
    topicStore.add(draft());
    setEditor(EMPTY_EDITOR);
    setNotice(null);
  };

  const onImport = async (input: HTMLInputElement) => {
    const file = input.files?.[0];
    if (!file) return;
    let result: ImportResult;
    if (file.size > MAX_IMPORT_BYTES) {
      result = { ok: false, code: "too_large" };
    } else {
      try {
        result = importTopics(await readText(file));
      } catch {
        result = { ok: false, code: "invalid_json" };
      }
    }
    if (!mounted.current) return;
    if (result.ok) {
      topicStore.replaceAll(result.topics);
      setNotice(null);
    } else {
      setNotice({ kind: "import", code: result.code });
    }
    try {
      input.value = "";
    } catch {
      // Some browsers refuse to reset a file input.
    }
  };

  const errorKey = (n: Notice) =>
    (n.kind === "import"
      ? `topics.import.error.${n.code}`
      : `topics.error.${n.code}`) as "topics.error.unknown";

  return (
    <section className="card" aria-labelledby={titleId}>
      <h2 id={titleId} className="card__title">
        {t("topics.title")}
      </h2>

      {notice ? (
        <div role="alert" className="provider__error">
          <p>{t(errorKey(notice))}</p>
          {notice.kind === "api" && notice.spans && notice.text !== undefined ? (
            <Highlighted text={notice.text} spans={notice.spans} />
          ) : null}
        </div>
      ) : null}
      {offline ? <p className="note">{t("topics.catalog.offline")}</p> : null}
      {busy ? <p role="status">{t("topics.working")}</p> : null}

      {catalog ? (
        <>
          <DomainSelect catalog={catalog} lang={lang} value={domainId} onChange={onDomain} />
          {domain ? (
            <>
              <SideSelect domain={domain} lang={lang} value={sideId} onChange={setSideId} />
              <TemplateTopicList
                domain={domain}
                side={sideId}
                lang={lang}
                off={off}
                onToggle={(id) => {
                  setOff((prev) => {
                    const next = new Set(prev);
                    if (!next.delete(id)) next.add(id);
                    return next;
                  });
                }}
              />
            </>
          ) : null}
        </>
      ) : null}

      <div className="provider__actions">
        <button
          type="button"
          className="button"
          disabled={busy || domainId === "" || documents.length === 0}
          onClick={() => void onSuggest()}
        >
          {t("topics.suggest.button")}
        </button>
      </div>
      <SuggestedTopics
        suggestions={suggestions}
        dropped={dropped}
        onAccept={(s) => {
          setEditor({ name: s.name, description: "", suggestedId: s.id, attributes: null });
          setSuggestions((list) => list.filter((x) => x.id !== s.id));
        }}
      />

      <OwnTopicEditor
        state={editor}
        busy={busy}
        canPropose={domainId !== ""}
        canConfirm={domainId !== "" && sideId !== "" && own.length < MAX_OWN_TOPICS}
        onChange={setEditor}
        onPropose={() => void onPropose()}
        onConfirm={onConfirm}
      />

      {own.length > 0 ? (
        <section>
          <h3>{t("topics.own.list")}</h3>
          <ul>
            {own.map((x) => (
              <li key={x.topic_id}>
                <span>{x.title}</span>{" "}
                <button
                  type="button"
                  className="button button--quiet button--small"
                  onClick={() => {
                    topicStore.remove(x.topic_id);
                  }}
                >
                  {t("topics.own.remove")}
                </button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className="provider__field provider__field--inline">
        <input
          id={persistId}
          type="checkbox"
          checked={persisted}
          onChange={(e) => {
            topicStore.setPersist(e.target.checked);
          }}
        />
        <label htmlFor={persistId}>{t("topics.persist.label")}</label>
      </div>

      <div className="provider__actions">
        <button
          type="button"
          className="button button--quiet"
          onClick={() => {
            download(exportTopics(topicStore.getTopics()));
          }}
        >
          {t("topics.export.button")}
        </button>
        <label htmlFor={importId}>{t("topics.import.label")}</label>
        <input
          id={importId}
          type="file"
          accept="application/json,.json"
          onChange={(e) => void onImport(e.currentTarget)}
        />
      </div>
    </section>
  );
}
