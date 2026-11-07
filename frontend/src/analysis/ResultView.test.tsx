/** S9-T4 AC3 — minimal result view: colour + icon + label, reasons, quotes by offsets, plain text. */
import { render, screen, within } from "@testing-library/react";
import i18next from "i18next";
import { createElement } from "react";
import { I18nextProvider } from "react-i18next";
import { beforeEach, describe, expect, it } from "vitest";
import en from "../i18n/locales/en.json";
import { setupI18n } from "../i18n";
import { evDone, evOther, evTopic, finding, value } from "../test/analysis-fakes";
import { flattenLocale } from "../test/locale-utils";
import { must } from "../test/topics-fakes";
import { DIGEST_A, DIGEST_B, maskedDoc } from "../test/tagging-fakes";
import { ResultView } from "./ResultView";

const EN = flattenLocale(en);
const t = (k: string): string => String(EN[k]);

type R = Record<string, unknown>;
const result = (label: string, over: R = {}): R => ({
  label,
  digest: label === "A" ? DIGEST_A : DIGEST_B,
  complete: true,
  done: evDone(),
  topics: [],
  others: [],
  error: null,
  ...over,
});
const DOCS = [maskedDoc("A", DIGEST_A), maskedDoc("B", DIGEST_B)];

async function show(results: R[], extra: R = {}, docs = DOCS) {
  await setupI18n();
  return render(
    createElement(
      I18nextProvider,
      { i18n: i18next },
      createElement(ResultView, {
        results,
        documents: docs,
        topicNames: { deductible: "Deductible" },
        ...extra,
      } as never),
    ),
  );
}
const topicWith = (over: R) => [evTopic("deductible", over)];

beforeEach(() => document.body.replaceChildren());

describe("findings", () => {
  it.each(["green", "yellow", "red"])(
    "test_%s_finding_has_colour_icon_and_text_label",
    async (rating) => {
      await show([result("A", { topics: topicWith({ findings: [finding({ rating })] }) })]);
      const f = document.querySelector<HTMLElement>("[data-finding]");
      expect(f?.dataset.rating).toBe(rating);
      expect(f?.querySelector("[data-rating-icon]")?.getAttribute("aria-hidden")).toBe("true");
      expect(f?.textContent).toContain(t(`analysis.rating.${rating}`));
    },
  );

  it("test_reason_codes_show_as_text_before_the_model_explanation", async () => {
    await show([
      result("A", {
        topics: topicWith({
          findings: [
            finding({
              rating: "yellow",
              reasons: ["check_exceptions", "number_mismatch"],
              explanation: "Model says fine.",
            }),
          ],
        }),
      }),
    ]);
    const f = must(document.querySelector<HTMLElement>("[data-finding]"));
    const reasons = f.querySelectorAll<HTMLElement>("[data-reason]");
    expect(Array.from(reasons).map((r) => r.dataset.reason)).toEqual([
      "check_exceptions",
      "number_mismatch",
    ]);
    expect(reasons[0]?.textContent).toBe(t("analysis.reason.check_exceptions"));
    const expl = within(f).getByText("Model says fine.");
    expect(
      reasons[1]?.compareDocumentPosition(expl) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("test_withheld_explanation_shows_the_translated_notice_not_the_code", async () => {
    await show([
      result("A", {
        topics: topicWith({
          findings: [finding({ rating: "yellow", explanation: "explanation_withheld" })],
        }),
      }),
    ]);
    expect(screen.queryByText("explanation_withheld")).toBeNull();
    expect(screen.getByText(t("analysis.explanationWithheld"))).toBeTruthy();
  });

  it("test_unverified_finding_is_labelled", async () => {
    await show([
      result("A", {
        topics: topicWith({ findings: [finding({ rating: "yellow", unverified: true })] }),
      }),
    ]);
    expect(screen.getByText(t("analysis.unverified"))).toBeTruthy();
  });

  it("test_green_is_shown_yellow_with_reason_when_the_result_is_not_complete", async () => {
    await show([
      result("A", {
        complete: false,
        done: null,
        topics: topicWith({ findings: [finding({ rating: "green" })] }),
      }),
    ]);
    const f = document.querySelector<HTMLElement>("[data-finding]");
    expect(document.querySelector('[data-rating="green"]')).toBeNull();
    expect(f?.dataset.rating).toBe("yellow");
    expect(f?.querySelector('[data-reason="incomplete"]')).not.toBeNull();
    expect(screen.queryByText(t("analysis.rating.green"))).toBeNull();
  });

  it("test_green_is_shown_yellow_when_greens_are_not_allowed", async () => {
    await show([
      result("A", {
        done: evDone({ greens_allowed: false }),
        topics: topicWith({ findings: [finding({ rating: "green" })] }),
      }),
    ]);
    expect(document.querySelector('[data-rating="green"]')).toBeNull();
  });

  it("test_incomplete_notice_shows_for_an_incomplete_result", async () => {
    await show([result("A", { complete: false, done: null })]);
    expect(screen.getByTestId("result-incomplete-A").textContent).toContain(
      t("analysis.incompleteNotice"),
    );
  });

  it("test_complete_result_has_no_incomplete_notice", async () => {
    await show([result("A")]);
    expect(screen.queryByTestId("result-incomplete-A")).toBeNull();
  });

  it("test_other_findings_and_unrated_count", async () => {
    await show([
      result("A", {
        done: evDone({ unrated_other: 3, incomplete: true, greens_allowed: false }),
        others: [
          evOther({
            findings: [
              {
                clause: "c3",
                rating: "red",
                explanation: "Unilateral.",
                reasons: [],
                unverified: false,
                evidence: [["c3", 4, 20]],
                attached: [],
              },
            ],
          }),
        ],
      }),
    ]);
    const o = screen.getByTestId("result-other-A");
    expect(o.textContent).toContain(t("analysis.other.heading"));
    expect(within(o).getByText("Unilateral.")).toBeTruthy();
    expect(o.textContent).toContain("3");
    expect(o.querySelector('[data-rating="red"]')).not.toBeNull();
  });

  it("test_missing_topic_finding_shows_rating_and_text", async () => {
    await show([result("A", { topics: topicWith({ missing: { rating: "red" } }) })]);
    const m = screen.getByTestId("result-missing-deductible-A");
    expect(m.textContent).toContain(t("analysis.rating.red"));
    expect(m.textContent).toContain(t("analysis.missing.red"));
  });

  it("test_not_analyzed_topic_is_yellow_with_the_reason_text", async () => {
    await show([result("A", { topics: topicWith({ state: "not_analyzed", reason: "timeout" }) })]);
    const s = screen.getByTestId("result-topicstate-deductible-A");
    expect(s.textContent).toContain(t("analysis.topic.state.not_analyzed"));
    expect(s.textContent).toContain(t("analysis.topic.reason.timeout"));
    expect(
      s.closest("[data-rating]")?.getAttribute("data-rating") ?? s.getAttribute("data-rating"),
    ).toBe("yellow");
  });
});

describe("quotes", () => {
  it("test_quote_is_cut_from_the_browsers_own_clause_text_by_offsets", async () => {
    // c1 = "1.1. The deductible is 5 percent."
    await show([
      result("A", { topics: topicWith({ findings: [finding({ evidence: [["c1", 6, 32]] })] }) }),
    ]);
    const q = document.querySelector("[data-quote]");
    expect(q?.textContent).toBe("The deductible is 5 percent");
  });

  it("test_quote_text_never_comes_from_the_server_event", async () => {
    await show([
      result("A", { topics: topicWith({ findings: [{ ...finding(), quote: "SERVER TEXT" }] }) }),
    ]);
    expect(document.body.textContent).not.toContain("SERVER TEXT");
  });

  it.each([
    ["unknown clause", [["zz", 0, 3]]],
    ["end beyond text", [["c1", 0, 999]]],
    ["start after end", [["c1", 9, 3]]],
    ["negative start", [["c1", -1, 3]]],
  ])("test_bad_span_%s_shows_no_quote_and_does_not_crash", async (_n, evidence) => {
    await show([result("A", { topics: topicWith({ findings: [finding({ evidence })] }) })]);
    expect(document.querySelector("[data-quote]")).toBeNull();
    expect(document.querySelector("[data-finding]")).not.toBeNull();
  });

  it("test_quote_uses_the_clause_of_the_same_document", async () => {
    const docs = [
      maskedDoc("A", DIGEST_A, ["AAAA first"]),
      maskedDoc("B", DIGEST_B, ["BBBB second"]),
    ];
    await show(
      [
        result("A", { topics: topicWith({ findings: [finding({ evidence: [["c1", 0, 4]] })] }) }),
        result("B", { topics: topicWith({ findings: [finding({ evidence: [["c1", 0, 4]] })] }) }),
      ],
      {},
      docs,
    );
    const qs = Array.from(document.querySelectorAll("[data-quote]")).map((q) => q.textContent);
    expect(qs.sort()).toEqual(["AAAA", "BBBB"]);
  });
});

describe("plain text only", () => {
  const EVIL = [
    "<script>window.__x=1</script>",
    '<img src=x onerror="window.__x=1">',
    "[click me](https://evil.example/steal)",
    "https://evil.example/plain",
  ];
  it.each(EVIL)("test_explanation_%s_is_text_not_markup", async (evil) => {
    await show([
      result("A", {
        topics: topicWith({ findings: [finding({ rating: "yellow", explanation: evil })] }),
      }),
    ]);
    expect(document.querySelector("script, img, a, iframe")).toBeNull();
    expect(document.body.textContent).toContain(evil);
  });

  it("test_clause_text_with_markup_is_rendered_as_text_in_the_quote", async () => {
    const evil = '<img src=x onerror="window.__x=1">';
    const docs = [maskedDoc("A", DIGEST_A, [evil])];
    await show(
      [
        result("A", {
          topics: topicWith({ findings: [finding({ evidence: [["c1", 0, evil.length]] })] }),
        }),
      ],
      {},
      docs,
    );
    expect(document.querySelector("img, script, a")).toBeNull();
    expect(document.querySelector("[data-quote]")?.textContent).toBe(evil);
  });

  it("test_text_value_with_markup_is_text", async () => {
    await show([
      result("A", {
        topics: topicWith({
          values: [
            value({
              attribute: "note",
              value: { type: "text", text: "<b>x</b> [l](http://e.example)" },
            }),
          ],
        }),
      }),
    ]);
    expect(document.querySelector("b, a")).toBeNull();
    expect(document.body.textContent).toContain("<b>x</b> [l](http://e.example)");
  });

  it("test_topic_name_with_markup_is_text", async () => {
    await show([result("A", { topics: topicWith({}) })], {
      topicNames: { deductible: "<i>Name</i>" },
    });
    expect(document.querySelector("i")).toBeNull();
    expect(screen.getByTestId("result-topic-deductible").textContent).toContain("<i>Name</i>");
  });
});

describe("values and comparison", () => {
  const v = (n: number, over: R = {}) =>
    value({ attribute: "amount", value: { type: "amount", number: n, currency: "UAH" }, ...over });
  const two = (a: R, b: R, extra: R = {}) =>
    show(
      [
        result("A", { topics: topicWith({ values: [a] }) }),
        result("B", { topics: topicWith({ values: [b] }) }),
      ],
      extra,
    );
  const cell = (label: string) =>
    must(
      screen
        .getByTestId("result-attr-deductible-amount")
        .querySelector<HTMLElement>(`[data-doc="${label}"]`),
    );
  const marks = () =>
    Array.from(document.querySelectorAll<HTMLElement>("[data-mark]")).map((m) => m.dataset.mark);

  it("test_values_show_number_and_unit", async () => {
    await two(v(5000), v(8000));
    expect(cell("A").textContent).toContain("5000 UAH");
    expect(cell("B").textContent).toContain("8000 UAH");
  });

  it("test_direction_gives_better_and_worse_with_icon_and_text", async () => {
    await two(v(5000), v(8000), { directions: { "deductible/amount": "lower_better" } });
    expect(cell("A").querySelector("[data-mark]")?.getAttribute("data-mark")).toBe("better");
    expect(cell("B").querySelector("[data-mark]")?.getAttribute("data-mark")).toBe("worse");
    const m = must(cell("A").querySelector("[data-mark]"));
    expect(m.querySelector("[data-mark-icon]")?.getAttribute("aria-hidden")).toBe("true");
    expect(m.textContent).toContain(t("analysis.mark.better"));
  });

  it("test_no_direction_gives_different_never_better", async () => {
    await two(v(5000), v(8000));
    expect(marks()).toEqual(["different", "different"]);
  });

  it("test_not_confirmed_value_hides_the_number_and_is_not_compared", async () => {
    await two(v(5000, { status: "not_confirmed" }), v(5000), {
      directions: { "deductible/amount": "lower_better" },
    });
    expect(cell("A").textContent).toContain(t("analysis.value.not_confirmed"));
    expect(cell("A").textContent).not.toContain("5000");
    expect(marks()).toEqual([]);
  });

  it("test_not_stated_value_is_labelled_and_not_compared", async () => {
    await two(value({ value: { type: "not_stated" } }), v(5000));
    expect(cell("A").textContent).toContain(t("analysis.value.not_stated"));
    expect(marks()).toEqual([]);
  });

  it("test_different_currencies_show_the_unit_note_and_no_marks", async () => {
    await two(v(5000), value({ value: { type: "amount", number: 100, currency: "USD" } }));
    expect(screen.getByTestId("result-note-deductible-amount").textContent).toContain(
      t("analysis.notComparable.unit"),
    );
    expect(marks()).toEqual([]);
  });

  it("test_text_values_show_side_by_side_with_compare_yourself", async () => {
    const tx = (s: string) => value({ attribute: "amount", value: { type: "text", text: s } });
    await two(tx("ten days"), tx("two weeks"));
    expect(cell("A").textContent).toContain("ten days");
    expect(cell("B").textContent).toContain("two weeks");
    expect(screen.getByTestId("result-note-deductible-amount").textContent).toContain(
      t("analysis.compareYourself"),
    );
    expect(marks()).toEqual([]);
  });

  it("test_incomplete_document_is_not_analyzed_and_gets_no_marks", async () => {
    await show(
      [
        result("A", { topics: topicWith({ values: [v(5000)] }) }),
        result("B", { complete: false, done: null, topics: topicWith({ values: [v(8000)] }) }),
      ],
      { directions: { "deductible/amount": "lower_better" } },
    );
    expect(cell("B").textContent).toContain(t("analysis.value.not_analyzed"));
    expect(cell("B").textContent).not.toContain("8000");
    expect(marks()).toEqual([]);
  });

  it("test_value_under_a_document_cap_is_never_better", async () => {
    await show(
      [
        result("A", {
          done: evDone({ greens_allowed: false }),
          topics: topicWith({ values: [v(5000)] }),
        }),
        result("B", { topics: topicWith({ values: [v(8000)] }) }),
      ],
      { directions: { "deductible/amount": "lower_better" } },
    );
    expect(marks()).not.toContain("better");
    expect(marks()).not.toContain("worse");
  });
});

it("test_no_html_sinks_in_analysis_sources", async () => {
  const { readdirSync, readFileSync } = await import("node:fs");
  const files = readdirSync(__dirname).filter((f) => /\.tsx?$/.test(f) && !f.includes(".test."));
  expect(files).toContain("ResultView.tsx");
  for (const f of files)
    expect(readFileSync(`${__dirname}/${f}`, "utf8"), f).not.toMatch(
      /dangerouslySetInnerHTML|innerHTML|insertAdjacentHTML|document\.write/,
    );
});
