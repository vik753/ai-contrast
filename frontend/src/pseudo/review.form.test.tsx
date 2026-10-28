/**
 * S5b-T3 AC 1-5, UI part: the "Check replacements" step inside the upload form.
 * Fetch is intercepted for every endpoint; `/api/safety-check` is a mock (S5b-T2 builds it).
 *
 * ASSUMED UI (the implementation must match; names are test contract):
 * - Locale keys under `pseudo.*` (see `KEYS` in locales test) and
 *   `upload.preview.warning.{requisites_condition,placeholder_lookalike,masked_next_to_amount}`.
 * - Inside `region "Contract X"`: a button named `pseudo.checkReplacements` opens
 *   `data-testid="pseudo-review-X"`; a status element `data-testid="pseudo-status-X"`
 *   shows `pseudo.status.{notReviewed,ready,confirmAgain}` text.
 * - In the review: each clause is `[data-clause-id="cN"]` (plain text); each highlighted occurrence is
 *   `[data-entity-id="eN"]` holding the original text, the class label (`pseudo.class.<CLS>`) and the
 *   placeholder preview; it has a button `pseudo.unmaskOne` (when allowed).
 *   An entity panel `data-testid="pseudo-entity-eN"` holds a button `pseudo.unmaskAll`; when the
 *   entity cannot be unmasked the button is disabled, `aria-describedby` points to `pseudo.cannotUnmask`.
 * - Selecting text in a clause shows a button `pseudo.maskSelection`; then a combobox named
 *   `pseudo.maskClassLabel` (option values = class codes) and buttons `pseudo.maskOnlyThis` and
 *   `pseudo.maskAllEqual` (with `{{count}}`).
 * - `pseudo.everythingCorrect` button confirms; errors show in `role="alert"` with `pseudo.error.<code>`.
 * - Dropped requisites lines: `[data-requisites-action="drop"]` inside `<s>`/`<del>`;
 *   kept: `[data-requisites-action="keep"]` with the warning text. Neutralized: `[data-neutralized]`
 *   plus the text `pseudo.neutralized.explanation`. Pre-masked after a server answer: `[data-premasked]`.
 */
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import i18next from "i18next";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import enJson from "../i18n/locales/en.json";
import { resetBrowserEnv } from "../test/browser-env";
import { flattenLocale } from "../test/locale-utils";
import {
  BLOCKS,
  DETECTOR_VERSION,
  ENTITIES,
  EXPECTED_MASKED,
  SECRETS,
  fixtureReply,
  installRouter,
  occurrences,
  type RecordedRequest,
} from "../test/pseudo-fakes";
import {
  Servers,
  addFile,
  body,
  region,
  renderForm,
  segmentReply,
  settle,
  type WireBlock,
} from "../test/segment-fakes";
import { jsonResponse, makeFile } from "../test/upload-fakes";

const EN = flattenLocale(enJson) as Record<string, string>;
const t = (key: string): string => {
  const v = EN[key];
  if (typeof v !== "string") throw new Error(`missing en key ${key}`);
  return v;
};

const FILE_A = "secret-name-A.docx";
const FILE_B = "secret-name-B.docx";
const DOC_B: WireBlock[] = [body("Buyer Gamma LLC pays Anna Petrenko.")];
const B_ENTITIES = [
  { id: "e1", class: "ORG", precision: "normal", spans: occurrences(DOC_B, 0, "Gamma LLC") },
  { id: "e2", class: "PERSON", precision: "normal", spans: occurrences(DOC_B, 0, "Anna Petrenko") },
];

let servers: Servers;
let requests: RecordedRequest[];
let reply: (blocks: WireBlock[]) => Record<string, unknown>;
let safety: (body: Record<string, unknown>) => Response;
let safetyBodies: Record<string, unknown>[];
let consoleCalls: unknown[][];

const OK = () =>
  jsonResponse(200, { ok: true, detector_version: DETECTOR_VERSION, digest: "b".repeat(64) });

beforeEach(() => {
  resetBrowserEnv();
  sessionStorage.clear();
  servers = new Servers();
  safetyBodies = [];
  safety = OK;
  reply = (blocks) =>
    blocks[0]?.text === BLOCKS[0]?.text
      ? fixtureReply()
      : {
          ...segmentReply(blocks),
          detector_version: DETECTOR_VERSION,
          entities: B_ENTITIES,
          requisites: [],
          neutralized: [],
        };
  requests = installRouter({
    extract: (b) => {
      const auto = servers.extract.autoRespond;
      if (auto === null) throw new Error("no extract fake");
      return auto(b);
    },
    segment: (blocks) => jsonResponse(200, reply(blocks)),
    safety: (b) => {
      safetyBodies.push(b);
      return safety(b);
    },
  });
  consoleCalls = [];
  for (const m of ["log", "info", "warn", "error", "debug"] as const) {
    vi.spyOn(console, m).mockImplementation((...args: unknown[]) => {
      consoleCalls.push(args);
    });
  }
});

afterEach(async () => {
  vi.unstubAllGlobals();
  await i18next.changeLanguage("en");
  resetBrowserEnv();
});

async function load(label = "A", blocks: WireBlock[] = BLOCKS, name = FILE_A) {
  const file = makeFile(name, { content: `content ${name}` });
  addFile(servers, label, file, blocks);
  await waitFor(() => {
    expect(
      within(region(label)).getByRole("button", { name: t("pseudo.checkReplacements") }),
    ).toBeTruthy();
  });
}

async function open(label = "A") {
  act(() => {
    fireEvent.click(
      within(region(label)).getByRole("button", { name: t("pseudo.checkReplacements") }),
    );
  });
  return screen.findByTestId(`pseudo-review-${label}`);
}

const status = (label = "A") => screen.getByTestId(`pseudo-status-${label}`).textContent;
const click = (el: HTMLElement) => act(() => void fireEvent.click(el));
const button = (root: HTMLElement, key: string) =>
  within(root).getByRole("button", { name: t(key) });
const confirm = async (review: HTMLElement) => {
  click(button(review, "pseudo.everythingCorrect"));
  await settle(20);
};
const marks = (review: HTMLElement, id: string) =>
  Array.from(review.querySelectorAll<HTMLElement>(`[data-entity-id="${id}"]`));

function assertNoLeak(extraAllowed: string[] = []) {
  const secrets = SECRETS.filter((s) => !extraAllowed.includes(s));
  for (const b of safetyBodies) {
    const raw = JSON.stringify(b);
    for (const s of secrets) expect(raw, `safety body leaks ${s}`).not.toContain(s);
    expect(raw).not.toContain("secret-name");
  }
  for (const r of requests) {
    if (typeof r.body === "string") {
      expect(r.body).not.toContain("secret-name");
      if (!r.url.includes("/api/segment")) {
        for (const s of secrets) expect(r.body).not.toContain(s);
      } else {
        expect(r.body).not.toMatch(/\[[A-Z]\.[A-Z_]+_\d+\]/); // no placeholder / mapping in segment bodies
      }
    }
  }
  const store = JSON.stringify([{ ...localStorage }, { ...sessionStorage }, location.href]);
  const logs = JSON.stringify(consoleCalls);
  const live = Array.from(document.querySelectorAll("[aria-live], [role=status], [role=alert]"))
    .map((e) => e.textContent)
    .join("|");
  for (const s of secrets) {
    expect(store, `storage/url leaks ${s}`).not.toContain(s);
    expect(logs, `console leaks ${s}`).not.toContain(s);
    expect(live, `announcement leaks ${s}`).not.toContain(s);
  }
}

describe("labels and the mandatory step", () => {
  it("test_contract_not_ready_before_replacements_are_confirmed", async () => {
    await renderForm();
    await load();
    expect(status()).toBe(t("pseudo.status.notReviewed"));
    expect(safetyBodies).toHaveLength(0);
  });

  it("test_labels_follow_contract_order_and_reach_the_safety_check", async () => {
    await renderForm();
    act(() => {
      fireEvent.click(screen.getAllByRole("button", { name: /add contract/i })[0] as HTMLElement);
    });
    await load("A");
    await load("B", DOC_B, FILE_B);
    const reviewB = await open("B");
    expect(reviewB.textContent).toContain("[B.ORG_1]");
    expect(reviewB.textContent).not.toContain("[A.");
    await confirm(reviewB);
    expect(safetyBodies[0]?.label).toBe("B");
    expect(JSON.stringify(safetyBodies[0])).toContain("[B.PERSON_1]");
    expect(JSON.stringify(safetyBodies[0])).not.toContain(FILE_B);
  });

  it("test_file_name_never_appears_in_masked_text_or_requests", async () => {
    await renderForm();
    await load();
    await confirm(await open());
    assertNoLeak();
  });
});

describe("highlighting", () => {
  it("test_every_entity_occurrence_is_highlighted_with_class_label_and_placeholder", async () => {
    await renderForm();
    await load();
    const review = await open();
    const john = marks(review, "e1");
    expect(john).toHaveLength(2);
    for (const m of john) {
      expect(m.textContent).toContain("John Smith");
      expect(m.textContent).toContain(t("pseudo.class.PERSON"));
      expect(m.textContent).toContain("[A.PERSON_1]");
    }
    expect(marks(review, "e3")[0]?.textContent).toContain("[A.ORG_1]");
    expect(marks(review, "e4")[0]?.textContent).toContain(t("pseudo.class.EMAIL"));
  });

  it("test_contract_text_is_rendered_as_plain_text_only", async () => {
    const evil: WireBlock[] = [
      body(
        'Seller ACME LLC <script>alert(1)</script> <img src=x onerror="alert(2)"> [click](https://evil.example) pays.',
      ),
    ];
    reply = (blocks) => ({
      ...segmentReply(blocks),
      detector_version: DETECTOR_VERSION,
      entities: [
        { id: "e1", class: "ORG", precision: "normal", spans: occurrences(evil, 0, "ACME LLC") },
      ],
      requisites: [],
      neutralized: [],
    });
    await renderForm();
    await load("A", evil);
    const review = await open();
    expect(review.querySelector("script, img, a, iframe, svg")).toBeNull();
    expect(review.querySelector("[onerror]")).toBeNull();
    expect(review.textContent).toContain("<script>alert(1)</script>");
    expect(review.textContent).toContain("<img src=x");
    expect(review.textContent).toContain("[click](https://evil.example)");
  });

  it("test_dropped_requisites_line_is_struck_through_and_kept_line_has_warning", async () => {
    const blocks = [
      body("Parties"),
      body("Ivanov I.I. +380501234567"),
      body("Seller waives all claims."),
    ];
    reply = (bl) => {
      const r = segmentReply(bl) as { clauses: Record<string, unknown>[] };
      r.clauses = [
        { ...r.clauses[0] },
        {
          ...r.clauses[1],
          section_kind: "requisites",
          spans: [
            [1, 0, 25],
            [2, 0, 25],
          ],
        },
      ];
      return {
        ...r,
        detector_version: DETECTOR_VERSION,
        entities: [{ id: "e1", class: "PERSON", precision: "normal", spans: [[1, 0, 10]] }],
        requisites: [
          {
            clause: "c2",
            lines: [
              { span: [1, 0, 25], action: "drop" },
              { span: [2, 0, 25], action: "keep" },
            ],
          },
        ],
        warnings: [{ code: "requisites_condition", clause: "c2" }],
        neutralized: [],
      };
    };
    await renderForm();
    await load("A", blocks);
    const review = await open();
    const dropped = review.querySelector<HTMLElement>('[data-requisites-action="drop"]');
    const kept = review.querySelector<HTMLElement>('[data-requisites-action="keep"]');
    expect(dropped?.closest("s, del, strike")).not.toBeNull();
    expect(kept?.closest("s, del, strike") ?? null).toBeNull();
    expect(kept?.textContent).toContain("Seller waives all claims.");
    expect(review.textContent).toContain(t("upload.preview.warning.requisites_condition"));
  });

  it("test_dropped_line_is_absent_from_the_safety_check_text", async () => {
    const blocks = [body("Parties"), body("Ivanov I.I."), body("Seller waives all claims.")];
    reply = (bl) => {
      const r = segmentReply(bl) as { clauses: Record<string, unknown>[] };
      r.clauses = [
        { ...r.clauses[0] },
        {
          ...r.clauses[1],
          section_kind: "requisites",
          spans: [
            [1, 0, 11],
            [2, 0, 25],
          ],
        },
      ];
      return {
        ...r,
        detector_version: DETECTOR_VERSION,
        entities: [{ id: "e1", class: "PERSON", precision: "normal", spans: [[1, 0, 10]] }],
        requisites: [
          {
            clause: "c2",
            lines: [
              { span: [1, 0, 11], action: "drop" },
              { span: [2, 0, 25], action: "keep" },
            ],
          },
        ],
        neutralized: [],
      };
    };
    await renderForm();
    await load("A", blocks);
    await confirm(await open());
    const clauses = safetyBodies[0]?.clauses as { id: string; text: string }[];
    expect(clauses.find((c) => c.id === "c2")?.text).toBe("Seller waives all claims.");
    assertNoLeak(["John Smith"]);
  });

  it("test_neutralized_lookalike_is_shown_with_explanation", async () => {
    const blocks = [body("Seller ⟦ORG_2⟧ pays on time.")];
    reply = (bl) => ({
      ...segmentReply(bl),
      detector_version: DETECTOR_VERSION,
      entities: [],
      requisites: [],
      neutralized: [[0, 7, 14]],
      warnings: [{ code: "placeholder_lookalike", clause: "c1" }],
    });
    await renderForm();
    await load("A", blocks);
    const review = await open();
    const item = review.querySelector<HTMLElement>("[data-neutralized]");
    expect(item?.textContent).toContain("⟦ORG_2⟧");
    expect(review.textContent).toContain(t("pseudo.neutralized.explanation"));
    expect(review.textContent).toContain(t("upload.preview.warning.placeholder_lookalike"));
  });
});

describe("unmask and manual masking", () => {
  it("test_high_entity_unmask_control_is_disabled_with_explanation", async () => {
    await renderForm();
    await load();
    const review = await open();
    for (const id of ["e4", "e5", "e6"]) {
      const btn = button(
        within(review).getByTestId(`pseudo-entity-${id}`),
        "pseudo.unmaskAll",
      ) as HTMLButtonElement;
      expect(btn.disabled).toBe(true);
      const described = btn.getAttribute("aria-describedby");
      expect(described).toBeTruthy();
      expect(document.getElementById(String(described))?.textContent).toBe(
        t("pseudo.cannotUnmask"),
      );
    }
  });

  it("test_unmask_all_shows_original_text_and_resets_nothing_else", async () => {
    await renderForm();
    await load();
    const review = await open();
    click(button(within(review).getByTestId("pseudo-entity-e1"), "pseudo.unmaskAll"));
    expect(marks(review, "e1")).toHaveLength(0);
    await confirm(review);
    const clauses = safetyBodies[0]?.clauses as { text: string }[];
    expect(clauses[0]?.text).toBe(
      "Seller [A.ORG_1] and John Smith agree. John Smith pays [A.ORG_1] within 30 days.",
    );
  });

  it("test_unmask_one_occurrence_sends_one_acknowledged_span", async () => {
    await renderForm();
    await load();
    const review = await open();
    click(button(marks(review, "e1")[1] as HTMLElement, "pseudo.unmaskOne"));
    await confirm(review);
    const [, s, e] = occurrences(BLOCKS, 0, "John Smith")[1] as number[];
    expect(safetyBodies[0]?.acknowledged_unmasked).toEqual([["c1", s, e]]);
    expect((safetyBodies[0]?.clauses as { text: string }[])[0]?.text).toContain(
      "[A.PERSON_1] agree. John Smith pays",
    );
  });

  it("test_masking_a_selection_masks_all_equal_occurrences_when_chosen", async () => {
    await renderForm();
    await load();
    const review = await open();
    const clause3 = review.querySelector<HTMLElement>('[data-clause-id="c3"]') as HTMLElement;
    const node = clause3.firstChild as Text; // "Ref code " is plain text before the tax id
    const range = document.createRange();
    range.setStart(node, 4);
    range.setEnd(node, 8);
    const sel = window.getSelection() as Selection;
    sel.removeAllRanges();
    sel.addRange(range);
    act(() => {
      document.dispatchEvent(new Event("selectionchange"));
      fireEvent.mouseUp(clause3);
    });
    click(button(review, "pseudo.maskSelection"));
    fireEvent.change(within(review).getByRole("combobox", { name: t("pseudo.maskClassLabel") }), {
      target: { value: "ADDRESS" },
    });
    const all = within(review).getByRole("button", {
      name: t("pseudo.maskAllEqual").replace("{{count}}", "2"),
    });
    click(all);
    await confirm(review);
    const texts = (safetyBodies[0]?.clauses as { text: string }[]).map((c) => c.text);
    expect(texts[1]).toBe("Contact: [A.EMAIL_1], tax [A.ADDRESS_1] [A.TAX_ID_1].");
    expect(texts[2]).toBe("Ref [A.ADDRESS_1] [A.TAX_ID_2] applies to [A.ORG_2].");
  });
});

describe("safety-check flow", () => {
  it("test_ok_answer_sends_expected_masked_text_and_marks_contract_ready", async () => {
    await renderForm();
    await load();
    await confirm(await open());
    expect(safetyBodies).toHaveLength(1);
    expect(safetyBodies[0]).toEqual({
      label: "A",
      detector_version: DETECTOR_VERSION,
      clauses: EXPECTED_MASKED.map((text, i) => ({ id: `c${String(i + 1)}`, text })),
      acknowledged_unmasked: [],
    });
    expect(status()).toBe(t("pseudo.status.ready"));
    assertNoLeak();
  });

  it("test_ready_only_after_ok_not_while_request_is_pending", async () => {
    let release: (r: Response) => void = () => undefined;
    const held = new Promise<Response>((resolve) => (release = resolve));
    safety = () => held as unknown as Response;
    await renderForm();
    await load();
    click(button(await open(), "pseudo.everythingCorrect"));
    await settle(10);
    expect(status()).not.toBe(t("pseudo.status.ready"));
    release(OK());
    await waitFor(() => expect(status()).toBe(t("pseudo.status.ready")));
  });

  it("test_unmasked_identifier_premasks_spans_and_requires_second_confirmation", async () => {
    const [, s, e] = occurrences(BLOCKS, 0, "30 days")[0] as number[];
    let n = 0;
    safety = () =>
      n++ === 0 ? jsonResponse(422, { error: "unmasked_identifier", spans: [["c1", s, e]] }) : OK();
    await renderForm();
    await load();
    const review = await open();
    await confirm(review);
    expect(status()).toBe(t("pseudo.status.confirmAgain"));
    expect(status()).not.toBe(t("pseudo.status.ready"));
    expect(review.querySelector("[data-premasked]")?.textContent).toContain("30 days");
    expect(safetyBodies).toHaveLength(1);
    await confirm(review);
    expect(safetyBodies).toHaveLength(2);
    const text = (safetyBodies[1]?.clauses as { text: string }[])[0]?.text ?? "";
    expect(text).not.toContain("30 days");
    expect(text).toMatch(/within \[A\.[A-Z_]+_[1-9]\d*\]\./);
    expect(status()).toBe(t("pseudo.status.ready"));
    assertNoLeak(["30 days"]);
  });

  it("test_second_confirmation_is_not_automatic_after_unmasked_identifier", async () => {
    const [, s, e] = occurrences(BLOCKS, 0, "30 days")[0] as number[];
    safety = () => jsonResponse(422, { error: "unmasked_identifier", spans: [["c1", s, e]] });
    await renderForm();
    await load();
    await confirm(await open());
    await settle(60);
    expect(safetyBodies).toHaveLength(1);
  });

  it("test_version_mismatch_resegments_and_restarts_the_review", async () => {
    let n = 0;
    safety = () => (n++ === 0 ? jsonResponse(409, { error: "detector_version_mismatch" }) : OK());
    await renderForm();
    await load();
    const review = await open();
    await confirm(review);
    await waitFor(() => {
      expect(requests.filter((r) => r.url.includes("/api/segment"))).toHaveLength(2);
    });
    await settle(30);
    expect(status()).toBe(t("pseudo.status.notReviewed"));
    expect(screen.getByRole("alert").textContent).toContain(
      t("pseudo.error.detector_version_mismatch"),
    );
    // The review starts again: a new "Everything is correct" is needed.
    expect(safetyBodies).toHaveLength(1);
    const again = await open();
    await confirm(again);
    expect(safetyBodies).toHaveLength(2);
    expect(status()).toBe(t("pseudo.status.ready"));
  });

  it("test_version_mismatch_discards_earlier_unmask_choices", async () => {
    let n = 0;
    safety = () => (n++ === 0 ? jsonResponse(409, { error: "detector_version_mismatch" }) : OK());
    await renderForm();
    await load();
    const review = await open();
    click(button(within(review).getByTestId("pseudo-entity-e1"), "pseudo.unmaskAll"));
    await confirm(review);
    await settle(40);
    const again = await open();
    expect(marks(again, "e1")).toHaveLength(2);
  });

  const ERROR_CASES: [number, string][] = [
    [422, "input_not_clean"],
    [422, "invalid_placeholder"],
    [422, "invalid_request"],
    [413, "request_too_large"],
    [503, "busy"],
    [504, "safety_timeout"],
  ];
  it.each(ERROR_CASES)("test_error_%i_%s_is_shown_with_its_own_message", async (status_, code) => {
    safety = () => jsonResponse(status_, { error: code });
    await renderForm();
    await load();
    await confirm(await open());
    expect(screen.getByRole("alert").textContent).toContain(t(`pseudo.error.${code}`));
    expect(status()).not.toBe(t("pseudo.status.ready"));
    assertNoLeak();
  });

  it("test_error_messages_are_distinct", () => {
    const keys = [
      "input_not_clean",
      "invalid_placeholder",
      "invalid_request",
      "request_too_large",
      "busy",
      "safety_timeout",
      "detector_version_mismatch",
      "network_error",
      "invalid_response",
    ];
    const texts = keys.map((k) => t(`pseudo.error.${k}`));
    expect(new Set(texts).size).toBe(keys.length);
  });

  it("test_network_failure_is_shown_and_contract_not_ready", async () => {
    safety = () => {
      throw new TypeError("offline");
    };
    await renderForm();
    await load();
    await confirm(await open());
    expect(status()).not.toBe(t("pseudo.status.ready"));
    expect(screen.getByRole("alert").textContent).toContain(t("pseudo.error.network_error"));
  });

  it("test_unmasked_occurrences_are_sent_as_acknowledged_unmasked", async () => {
    await renderForm();
    await load();
    const review = await open();
    click(button(within(review).getByTestId("pseudo-entity-e3"), "pseudo.unmaskAll"));
    await confirm(review);
    const spans = occurrences(BLOCKS, 0, "ACME LLC").map(([, s, e]) => ["c1", s, e]);
    expect(safetyBodies[0]?.acknowledged_unmasked).toEqual(spans);
  });
});

describe("readiness reset", () => {
  async function ready() {
    await renderForm();
    await load();
    const review = await open();
    await confirm(review);
    expect(status()).toBe(t("pseudo.status.ready"));
    return review;
  }

  it("test_unmask_after_ok_resets_readiness", async () => {
    const review = await ready();
    click(button(within(review).getByTestId("pseudo-entity-e1"), "pseudo.unmaskAll"));
    expect(status()).toBe(t("pseudo.status.notReviewed"));
  });

  it("test_manual_mask_after_ok_resets_readiness", async () => {
    const review = await ready();
    const clause3 = review.querySelector<HTMLElement>('[data-clause-id="c3"]') as HTMLElement;
    const node = clause3.firstChild as Text;
    const range = document.createRange();
    range.setStart(node, 0);
    range.setEnd(node, 3);
    const sel = window.getSelection() as Selection;
    sel.removeAllRanges();
    sel.addRange(range);
    act(() => {
      document.dispatchEvent(new Event("selectionchange"));
      fireEvent.mouseUp(clause3);
    });
    click(button(review, "pseudo.maskSelection"));
    fireEvent.change(within(review).getByRole("combobox", { name: t("pseudo.maskClassLabel") }), {
      target: { value: "ORG" },
    });
    click(button(review, "pseudo.maskOnlyThis"));
    expect(status()).toBe(t("pseudo.status.notReviewed"));
  });

  it("test_removing_the_file_after_ok_drops_the_review_and_readiness", async () => {
    await ready();
    act(() => {
      fireEvent.click(within(region("A")).getByRole("button", { name: /^remove (?!contract)/i }));
    });
    expect(screen.queryByTestId("pseudo-review-A")).toBeNull();
  });
});

describe("nothing leaks", () => {
  it("test_full_flow_leaves_no_original_value_in_storage_url_console_or_announcements", async () => {
    await renderForm();
    await load();
    const review = await open();
    click(button(marks(review, "e2")[0] as HTMLElement, "pseudo.unmaskOne"));
    await confirm(review);
    assertNoLeak(["Beta Inc"]);
  });

  it("test_every_request_goes_to_a_known_endpoint", async () => {
    await renderForm();
    await load();
    await confirm(await open());
    for (const r of requests) {
      expect(
        ["/api/extract", "/api/segment", "/api/safety-check"].some((u) => r.url.includes(u)),
      ).toBe(true);
    }
  });
});

describe("languages", () => {
  it.each(["uk", "ru"])("test_review_is_translated_in_%s", async (lng) => {
    await renderForm();
    await load();
    // Open first: `open` finds the region by its English name "Contract A".
    const review = await open();
    await i18next.changeLanguage(lng);
    const flat = flattenLocale((await import(`../i18n/locales/${lng}.json`)).default) as Record<
      string,
      string
    >;
    expect(flat["pseudo.everythingCorrect"]).not.toBe(t("pseudo.everythingCorrect"));
    expect(
      within(review).getByRole("button", { name: flat["pseudo.everythingCorrect"] as string }),
    ).toBeTruthy();
    expect(review.textContent).toContain(flat["pseudo.class.ORG"] as string);
    expect(ENTITIES.length).toBeGreaterThan(0);
  });
});
