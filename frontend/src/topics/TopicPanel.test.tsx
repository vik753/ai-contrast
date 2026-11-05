/** S7-T3 AC1, AC1a, AC3 — topic panel behaviour (English UI unless stated). */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import en from "../i18n/locales/en.json";
import uk from "../i18n/locales/uk.json";
import { flattenLocale } from "../test/locale-utils";
import { jsonResponse } from "../test/provider-fakes";
import { DOC, attr, bodyOf, must, stubTopicsFetch, type Router } from "../test/topics-fakes";
import type { TopicSelection } from "./types";

const EN = flattenLocale(en);
const UK = flattenLocale(uk);
let current: Record<string, unknown> = EN;
const text = (k: string): string => String(current[k]);
const KEY = "sk-CANARY-panel-9876";

interface Props {
  connection: { provider: string; model?: string; key?: string };
  turnstileToken?: string;
  documents: ReturnType<typeof DOC>[];
  onSelectionChange?: (s: TopicSelection) => void;
}

async function renderPanel(over: Partial<Props> = {}, lang: "en" | "uk" = "en") {
  current = lang === "en" ? EN : UK;
  vi.resetModules();
  const i18n = await import("../i18n/index");
  await i18n.setupI18n();
  if (lang !== "en") await i18n.changeLanguage(lang);
  const mod = (await import("./TopicPanel")) as { TopicPanel: ComponentType<Props> };
  const props: Props = {
    connection: { provider: "anthropic", model: "m1", key: KEY },
    documents: [DOC("Contract A"), DOC("Contract B")],
    ...over,
  };
  const r = render(<mod.TopicPanel {...props} />);
  await screen.findByRole("option", { name: lang === "en" ? "Car insurance" : "Автострахування" });
  return r;
}

const domainSelect = () => screen.getByLabelText<HTMLSelectElement>(text("topics.domain.label"));
const sideSelect = () => screen.getByLabelText<HTMLSelectElement>(text("topics.side.label"));
const pickDomain = (id: string) => fireEvent.change(domainSelect(), { target: { value: id } });
const btn = (k: string) => screen.getByRole("button", { name: text(k) });
const editor = () => screen.getByRole("group", { name: text("topics.own.heading") });
const nameBox = () => within(editor()).getByLabelText<HTMLInputElement>(text("topics.own.name"));
const descBox = () =>
  within(editor()).getByLabelText<HTMLInputElement>(text("topics.own.description"));
const type = (el: HTMLElement, value: string) => fireEvent.change(el, { target: { value } });
const li = (el: HTMLElement) => must(el.closest("li"));
const alertText = () => screen.getByRole("alert").textContent;

const SUGGEST_OK: Router = (c) =>
  c.url === "/api/topics/suggest"
    ? jsonResponse(200, {
        suggestions: [
          { id: "suggested_1", name: "Roadside help", description: "Tow truck rules" },
          { id: "suggested_2", name: "Glass cover", description: "Windscreen" },
        ],
        dropped: 1,
      })
    : undefined;

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("catalog in the panel (AC1)", () => {
  it("test_domain_list_shows_none_and_domains_in_ui_language", async () => {
    stubTopicsFetch();
    await renderPanel();
    expect([...domainSelect().options].map((o) => [o.value, o.textContent])).toEqual([
      ["", text("topics.domain.none")],
      ["kasko", "Car insurance"],
      ["lease", "Lease"],
    ]);
    expect(domainSelect().value).toBe("");
    expect(screen.queryByLabelText(text("topics.side.label"))).toBeNull();
  });

  it("test_sides_follow_the_domain", async () => {
    stubTopicsFetch();
    await renderPanel();
    pickDomain("kasko");
    expect([...sideSelect().options].map((o) => [o.value, o.textContent])).toEqual([
      ["insured", "Insured"],
      ["insurer", "Insurer"],
    ]);
    pickDomain("lease");
    expect([...sideSelect().options].map((o) => o.value)).toEqual(["tenant", "landlord"]);
  });

  it("test_template_topics_show_attributes_and_directions_for_the_side", async () => {
    stubTopicsFetch();
    await renderPanel();
    pickDomain("kasko");
    const item = li(screen.getByRole("checkbox", { name: "Deductible" }));
    expect(item.textContent).toContain("Deductible amount");
    expect(item.textContent).toContain(text("topics.direction.lower_better"));
    const theft = li(screen.getByRole("checkbox", { name: "Theft cover" }));
    expect(theft.textContent).toContain(text("topics.direction.ordered"));
    type(sideSelect(), "insurer");
    expect(item.textContent).toContain(text("topics.direction.higher_better"));
  });

  it("test_ui_language_uk_renders_catalog_names_in_ukrainian", async () => {
    stubTopicsFetch();
    await renderPanel({}, "uk");
    pickDomain("kasko");
    expect(screen.getByRole("checkbox", { name: "Франшиза" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Страхувальник" })).toBeTruthy();
    expect(screen.getByLabelText(text("topics.domain.label"))).toBeTruthy();
  });

  it("test_template_topics_selected_by_default_and_can_be_turned_off", async () => {
    stubTopicsFetch();
    const seen: TopicSelection[] = [];
    await renderPanel({ onSelectionChange: (s) => seen.push(s) });
    pickDomain("kasko");
    const all = () =>
      screen
        .getAllByRole("checkbox")
        .filter((c) =>
          /Deductible|Theft/.test(
            c.getAttribute("aria-label") ?? c.closest("li")?.textContent ?? "",
          ),
        );
    expect(all().every((c) => (c as HTMLInputElement).checked)).toBe(true);
    const last = () => must(seen[seen.length - 1]);
    expect(
      last()
        .catalog.map((r) => r.topic_id)
        .sort(),
    ).toEqual(["deductible", "theft"]);
    expect(last().catalog[0]).toMatchObject({
      domain: "kasko",
      side: "insured",
      lang: "en",
      catalog_version: "v-test-1",
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "Theft cover" }));
    expect(last().catalog.map((r) => r.topic_id)).toEqual(["deductible"]);
    expect(last().suggested).toEqual([]);
    expect(last().custom).toEqual([]);
  });
});

describe("suggested topics (AC1, AC1a)", () => {
  it("test_suggest_makes_one_call_per_document_with_masked_document", async () => {
    const { calls } = stubTopicsFetch(SUGGEST_OK);
    await renderPanel();
    pickDomain("kasko");
    fireEvent.click(btn("topics.suggest.button"));
    await screen.findAllByText("Roadside help");
    const s = calls.filter((c) => c.url === "/api/topics/suggest");
    expect(s).toHaveLength(2);
    expect(s.map((c) => (bodyOf(c).document as { label: string }).label).sort()).toEqual([
      "Contract A",
      "Contract B",
    ]);
    for (const c of s) {
      expect(bodyOf(c)).toMatchObject({ provider: "anthropic", domain: "kasko", side: "insured" });
      expect(c.headers.get("X-Provider-Key")).toBe(KEY);
      expect(c.body).not.toContain(KEY);
    }
  });

  it("test_dropped_count_is_shown_summed", async () => {
    stubTopicsFetch(SUGGEST_OK);
    await renderPanel();
    pickDomain("kasko");
    fireEvent.click(btn("topics.suggest.button"));
    await screen.findAllByText("Roadside help");
    expect(document.body.textContent).toContain(
      text("topics.suggest.dropped").replace("{{count}}", "2"),
    );
  });

  it("test_accepting_one_suggestion_leaves_description_empty_and_others_unaccepted", async () => {
    const seen: TopicSelection[] = [];
    const { calls } = stubTopicsFetch((c) => {
      if (c.url === "/api/topics/suggest")
        return jsonResponse(200, {
          suggestions: [
            { id: "suggested_1", name: "Roadside help", description: "Tow truck rules" },
          ],
          dropped: 0,
        });
      if (c.url === "/api/topics/propose-attributes")
        return jsonResponse(200, { attributes: [attr()], dropped: 0 });
      return undefined;
    });
    await renderPanel({ documents: [DOC("Contract A")], onSelectionChange: (s) => seen.push(s) });
    pickDomain("kasko");
    fireEvent.click(btn("topics.suggest.button"));
    const item = li(await screen.findByText("Roadside help"));
    expect(item.textContent).toContain("Tow truck rules");
    fireEvent.click(within(item).getByRole("button", { name: text("topics.suggest.accept") }));
    expect(nameBox().value).toBe("Roadside help");
    expect(descBox().value).toBe("");
    for (const el of document.querySelectorAll("input, textarea")) {
      expect((el as HTMLInputElement).value).not.toContain("Tow truck");
    }
    fireEvent.click(btn("topics.own.propose"));
    await screen.findByRole("list", { name: text("topics.attr.list") });
    const prop = must(calls.find((c) => c.url === "/api/topics/propose-attributes"));
    expect(bodyOf(prop).topic).toMatchObject({ origin: "suggested", description: "" });
    fireEvent.click(btn("topics.own.confirm"));
    const last = must(seen[seen.length - 1]);
    expect(last.suggested).toHaveLength(1);
    expect(last.suggested[0]).toMatchObject({ title: "Roadside help", description: "" });
    expect(last.custom).toEqual([]);
  });

  it("test_model_strings_render_as_plain_text_no_elements_no_links", async () => {
    stubTopicsFetch((c) =>
      c.url === "/api/topics/suggest"
        ? jsonResponse(200, {
            suggestions: [
              {
                id: "suggested_1",
                name: "<img src=x onerror=alert(1)>",
                description: "[click](http://evil.example) <script>alert(2)</script> <b>bold</b>",
              },
            ],
            dropped: 0,
          })
        : undefined,
    );
    const { container } = await renderPanel({ documents: [DOC("A")] });
    pickDomain("kasko");
    fireEvent.click(btn("topics.suggest.button"));
    await screen.findByText("<img src=x onerror=alert(1)>");
    expect(container.textContent).toContain("[click](http://evil.example)");
    expect(container.querySelector("img, script, a, b")).toBeNull();
    expect(container.querySelector("[onerror]")).toBeNull();
  });
});

describe("own topic flow (AC1)", () => {
  async function propose(attrs: unknown[]) {
    const stub = stubTopicsFetch((c) =>
      c.url === "/api/topics/propose-attributes"
        ? jsonResponse(200, { attributes: attrs, dropped: 0 })
        : undefined,
    );
    const seen: TopicSelection[] = [];
    await renderPanel({ onSelectionChange: (s) => seen.push(s) });
    pickDomain("kasko");
    type(nameBox(), "Roadside");
    type(descBox(), "Towing");
    fireEvent.click(btn("topics.own.propose"));
    await screen.findByRole("list", { name: text("topics.attr.list") });
    return { ...stub, seen };
  }
  const rows = () =>
    within(screen.getByRole("list", { name: text("topics.attr.list") })).getAllByRole("listitem");
  const dirOf = (row: HTMLElement) =>
    within(row).getByLabelText<HTMLSelectElement>(text("topics.attr.direction"));

  it("test_propose_sends_custom_topic_without_attributes_and_lists_editable_rows", async () => {
    const { calls } = await propose([
      attr({ id: "a1", label: "Limit" }),
      attr({ id: "a2", label: "Days", type: "duration", units: ["days"] }),
    ]);
    const req = must(calls.find((c) => c.url === "/api/topics/propose-attributes"));
    expect(bodyOf(req).topic).toMatchObject({
      origin: "custom",
      title: "Roadside",
      description: "Towing",
      attributes: [],
    });
    expect(rows()).toHaveLength(2);
    const first = within(must(rows()[0])).getByLabelText<HTMLInputElement>(
      text("topics.attr.label"),
    );
    expect(first.value).toBe("Limit");
    type(first, "Cap");
    expect(first.value).toBe("Cap");
    fireEvent.click(
      within(must(rows()[1])).getByRole("button", { name: text("topics.attr.remove") }),
    );
    expect(rows()).toHaveLength(1);
  });

  it("test_directions_start_at_none_even_if_model_sent_other", async () => {
    await propose([attr({ direction: "higher_better" }), attr({ id: "a2", direction: "none" })]);
    expect(rows().map((r) => dirOf(r).value)).toEqual(["none", "none"]);
  });

  it("test_direction_options_follow_attribute_type", async () => {
    await propose([
      attr({ id: "a1", type: "amount" }),
      attr({ id: "a2", type: "categories", values: ["x"], units: [] }),
      attr({ id: "a3", type: "text", units: [] }),
    ]);
    const opts = (i: number) => [...dirOf(must(rows()[i])).options].map((o) => o.value);
    expect(opts(0)).toEqual(["none", "lower_better", "higher_better"]);
    expect(opts(1)).toEqual(["none", "more_better", "fewer_better"]);
    expect(opts(2)).toEqual(["none"]);
  });

  it("test_confirm_keeps_client_chosen_direction_with_client_source", async () => {
    const { seen } = await propose([attr({ id: "a1" }), attr({ id: "a2", label: "Other" })]);
    type(dirOf(must(rows()[0])), "higher_better");
    fireEvent.click(btn("topics.own.confirm"));
    const t = must(must(seen[seen.length - 1]).custom[0]);
    expect(t).toMatchObject({ origin: "custom", title: "Roadside", description: "Towing" });
    expect(t.attributes.map((a) => [a.direction, a.direction_source])).toEqual([
      ["higher_better", "client"],
      ["none", "client"],
    ]);
  });

  it("test_proposed_attribute_markup_is_plain_text", async () => {
    await propose([attr({ label: "<b>bold</b> [x](http://evil.example)" })]);
    const input = within(must(rows()[0])).getByLabelText<HTMLInputElement>(
      text("topics.attr.label"),
    );
    expect(input.value).toBe("<b>bold</b> [x](http://evil.example)");
    expect(document.querySelector("b, a, img, script")).toBeNull();
  });
});

describe("errors (AC3)", () => {
  async function failPropose(status: number, body: unknown) {
    stubTopicsFetch((c) =>
      c.url === "/api/topics/propose-attributes" ? jsonResponse(status, body) : undefined,
    );
    await renderPanel();
    pickDomain("kasko");
    type(nameBox(), "Call Ivan Petrenko now");
    fireEvent.click(btn("topics.own.propose"));
    await screen.findByRole("alert");
  }

  it.each([
    "topic_flagged",
    "invalid_topic_text",
    "ai_bad_output",
    "free_quota_exhausted",
    "busy",
    "catalog_version_mismatch",
  ])("test_error_%s_shows_its_message", async (code) => {
    await failPropose(422, { error: code });
    expect(alertText()).toContain(text(`topics.error.${code}`));
    if (code.includes("_")) expect(alertText()).not.toContain(code);
  });

  it("test_unknown_server_text_is_never_shown", async () => {
    await failPropose(500, { error: "<b>boom</b>", detail: "secret detail" });
    expect(alertText()).toContain(text("topics.error.unknown"));
    expect(document.body.textContent).not.toContain("secret detail");
  });

  it("test_identifier_error_highlights_each_span", async () => {
    await failPropose(422, {
      error: "topic_contains_identifier",
      field: "title",
      spans: [[5, 18]],
    });
    expect(alertText()).toContain(text("topics.error.topic_contains_identifier"));
    const marks = [...document.querySelectorAll("mark")].map((m) => m.textContent);
    expect(marks).toEqual(["Ivan Petrenko"]);
  });

  it("test_suggest_error_is_shown_too", async () => {
    stubTopicsFetch((c) =>
      c.url === "/api/topics/suggest"
        ? jsonResponse(429, { error: "free_quota_exhausted" })
        : undefined,
    );
    await renderPanel();
    pickDomain("kasko");
    fireEvent.click(btn("topics.suggest.button"));
    await waitFor(() => expect(alertText()).toContain(text("topics.error.free_quota_exhausted")));
  });
});

describe("free pass reuse (AC1)", () => {
  it("test_pass_reused_after_first_token_and_replaced_by_new_one", async () => {
    let n = 0;
    const { calls } = stubTopicsFetch((c) => {
      if (c.url !== "/api/topics/propose-attributes") return undefined;
      n += 1;
      return jsonResponse(200, {
        attributes: [attr()],
        dropped: 0,
        ...(n <= 2 ? { free_pass: `pass-${n}` } : {}),
      });
    });
    await renderPanel({ connection: { provider: "free" }, turnstileToken: "tok-1" });
    pickDomain("kasko");
    type(nameBox(), "T");
    for (let i = 0; i < 3; i++) {
      fireEvent.click(btn("topics.own.propose"));
      await waitFor(() =>
        expect(calls.filter((c) => c.url.includes("propose")).length).toBe(i + 1),
      );
      await screen.findByRole("list", { name: text("topics.attr.list") });
    }
    const p = calls.filter((c) => c.url.includes("propose"));
    expect(bodyOf(must(p[0])).turnstile_token).toBe("tok-1");
    expect(must(p[0]).headers.get("X-Free-Pass")).toBeNull();
    expect(must(p[1]).headers.get("X-Free-Pass")).toBe("pass-1");
    expect(bodyOf(must(p[1]))).not.toHaveProperty("turnstile_token");
    expect(must(p[2]).headers.get("X-Free-Pass")).toBe("pass-2");
    for (const c of p) expect(c.headers.get("X-Provider-Key")).toBeNull();
  });
});

describe("confirm expands synonyms (AC1)", () => {
  it("test_confirm_calls_expand_synonyms_and_stores_the_synonyms", async () => {
    const seen: TopicSelection[] = [];
    const { calls } = stubTopicsFetch((c) => {
      if (c.url === "/api/topics/propose-attributes")
        return jsonResponse(200, { attributes: [attr()], dropped: 0 });
      if (c.url === "/api/topics/expand-synonyms")
        return jsonResponse(200, {
          synonyms_en: ["towing", "tow"],
          synonyms_uk: ["евакуац"],
          synonyms_ru: ["эвакуац"],
          dropped: 0,
        });
      return undefined;
    });
    await renderPanel({ onSelectionChange: (s) => seen.push(s) });
    pickDomain("kasko");
    type(nameBox(), "Roadside");
    fireEvent.click(btn("topics.own.propose"));
    await screen.findByRole("list", { name: text("topics.attr.list") });
    fireEvent.click(btn("topics.own.confirm"));
    await waitFor(() =>
      expect(calls.filter((c) => c.url === "/api/topics/expand-synonyms")).toHaveLength(1),
    );
    const req = must(calls.find((c) => c.url === "/api/topics/expand-synonyms"));
    expect(bodyOf(req).topic).toMatchObject({ title: "Roadside", origin: "custom" });
    expect(req.headers.get("X-Provider-Key")).toBe(KEY);
    await waitFor(() => {
      const t = must(seen[seen.length - 1]).custom[0];
      expect(t).toMatchObject({
        synonyms_en: ["towing", "tow"],
        synonyms_uk: ["евакуац"],
        synonyms_ru: ["эвакуац"],
      });
    });
  });
});

describe("storage controls (AC2)", () => {
  it("test_persist_checkbox_default_off_and_toggles_local_storage", async () => {
    stubTopicsFetch((c) =>
      c.url === "/api/topics/propose-attributes"
        ? jsonResponse(200, { attributes: [attr()], dropped: 0 })
        : undefined,
    );
    await renderPanel();
    pickDomain("kasko");
    type(nameBox(), "Saved one");
    fireEvent.click(btn("topics.own.propose"));
    await screen.findByRole("list", { name: text("topics.attr.list") });
    fireEvent.click(btn("topics.own.confirm"));
    const box = screen.getByRole<HTMLInputElement>("checkbox", {
      name: text("topics.persist.label"),
    });
    expect(box.checked).toBe(false);
    expect(localStorage.getItem("aic.topics.v1")).toBeNull();
    fireEvent.click(box);
    expect(localStorage.getItem("aic.topics.v1")).toContain("Saved one");
    fireEvent.click(box);
    expect(localStorage.getItem("aic.topics.v1")).toBeNull();
  });

  it("test_import_ui_rejects_oversized_file_and_accepts_valid_one", async () => {
    stubTopicsFetch();
    await renderPanel();
    const input = screen.getByLabelText<HTMLInputElement>(text("topics.import.label"));
    const big = new File(["x".repeat(262145)], "t.json", { type: "application/json" });
    fireEvent.change(input, { target: { files: [big] } });
    await waitFor(() => expect(alertText()).toContain(text("topics.import.error.too_large")));
    const { topic } = await import("../test/topics-fakes");
    const ok = new File(
      [JSON.stringify({ version: 1, topics: [topic({ title: "Imported<b>" })] })],
      "t.json",
    );
    fireEvent.change(input, { target: { files: [ok] } });
    await screen.findByText("Imported<b>");
    expect(document.querySelector("b")).toBeNull();
  });
});
