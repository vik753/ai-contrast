/**
 * S5b-T3 (own tests): two contracts side by side. Removing contract A keeps B's review and
 * readiness and drops everything of A; no safety-check body carries an original value.
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
const t = (key: string): string => EN[key] ?? key;

const DOC_B: WireBlock[] = [body("Buyer Gamma LLC pays Anna Petrenko.")];
const B_SECRETS = ["Gamma LLC", "Anna Petrenko", "Gamma", "Petrenko"];

let servers: Servers;
let requests: RecordedRequest[];
let safetyBodies: Record<string, unknown>[];

beforeEach(() => {
  resetBrowserEnv();
  servers = new Servers();
  safetyBodies = [];
  requests = installRouter({
    extract: (b) => {
      const auto = servers.extract.autoRespond;
      if (auto === null) throw new Error("no extract fake");
      return auto(b);
    },
    segment: (blocks) =>
      jsonResponse(
        200,
        blocks[0]?.text === BLOCKS[0]?.text
          ? fixtureReply()
          : {
              ...segmentReply(blocks),
              detector_version: DETECTOR_VERSION,
              entities: [
                {
                  id: "e1",
                  class: "ORG",
                  precision: "normal",
                  spans: occurrences(DOC_B, 0, "Gamma LLC"),
                },
                {
                  id: "e2",
                  class: "PERSON",
                  precision: "normal",
                  spans: occurrences(DOC_B, 0, "Anna Petrenko"),
                },
              ],
              requisites: [],
              neutralized: [],
            },
      ),
    safety: (b) => {
      safetyBodies.push(b);
      return jsonResponse(200, {
        ok: true,
        detector_version: DETECTOR_VERSION,
        digest: "c".repeat(64),
      });
    },
  });
});

afterEach(async () => {
  vi.unstubAllGlobals();
  await i18next.changeLanguage("en");
  resetBrowserEnv();
});

async function load(label: string, blocks: WireBlock[], name: string) {
  addFile(servers, label, makeFile(name, { content: name }), blocks);
  await waitFor(() => {
    expect(
      within(region(label)).getByRole("button", { name: t("pseudo.checkReplacements") }),
    ).toBeTruthy();
  });
}

async function reviewAndConfirm(label: string): Promise<HTMLElement> {
  act(() => {
    fireEvent.click(
      within(region(label)).getByRole("button", { name: t("pseudo.checkReplacements") }),
    );
  });
  const review = await screen.findByTestId(`pseudo-review-${label}`);
  act(() => {
    fireEvent.click(within(review).getByRole("button", { name: t("pseudo.everythingCorrect") }));
  });
  await settle(20);
  return review;
}

describe("two contracts", () => {
  async function both() {
    await renderForm();
    await load("A", BLOCKS, "a.docx");
    await load("B", DOC_B, "b.docx");
    await reviewAndConfirm("A");
    await reviewAndConfirm("B");
    expect(screen.getByTestId("pseudo-status-A").textContent).toBe(t("pseudo.status.ready"));
    expect(screen.getByTestId("pseudo-status-B").textContent).toBe(t("pseudo.status.ready"));
  }

  it("test_removing_contract_a_keeps_b_review_and_readiness_and_drops_a", async () => {
    await both();
    const before = safetyBodies.length;
    // Two contracts is the minimum: add a third so that A can be removed.
    const [add] = screen.getAllByRole("button", { name: /add contract/i });
    if (add === undefined) throw new Error("no add button");
    act(() => {
      fireEvent.click(add);
    });
    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "Remove Contract A" }));
    });
    await settle(30);
    // B is now the first contract: label A, review and readiness intact.
    expect(screen.getByTestId("pseudo-status-A").textContent).toBe(t("pseudo.status.ready"));
    const review = screen.getByTestId("pseudo-review-A");
    expect(review.textContent).toContain("Gamma LLC");
    expect(review.textContent).toContain("[A.ORG_1]");
    expect(review.textContent).not.toContain("[B.");
    // Nothing of the removed contract is left in the page, and nothing was sent again.
    for (const secret of SECRETS) {
      expect(document.body.textContent).not.toContain(secret);
    }
    expect(safetyBodies).toHaveLength(before);
  });

  it("test_edit_in_one_contract_does_not_reset_the_other", async () => {
    await both();
    const reviewA = screen.getByTestId("pseudo-review-A");
    act(() => {
      fireEvent.click(
        within(within(reviewA).getByTestId("pseudo-entity-e1")).getByRole("button", {
          name: t("pseudo.unmaskAll"),
        }),
      );
    });
    expect(screen.getByTestId("pseudo-status-A").textContent).toBe(t("pseudo.status.notReviewed"));
    expect(screen.getByTestId("pseudo-status-B").textContent).toBe(t("pseudo.status.ready"));
  });
});

describe("request bodies", () => {
  it("test_no_safety_body_holds_an_original_value_and_none_holds_the_other_contract", async () => {
    await renderForm();
    await load("A", BLOCKS, "a.docx");
    await load("B", DOC_B, "b.docx");
    await reviewAndConfirm("A");
    await reviewAndConfirm("B");
    expect(safetyBodies).toHaveLength(2);
    const [a, b] = safetyBodies.map((x) => JSON.stringify(x));
    for (const secret of [...SECRETS, ...B_SECRETS]) {
      expect(a).not.toContain(secret);
      expect(b).not.toContain(secret);
    }
    expect(a).toContain("[A.ORG_1]");
    expect(b).toContain("[B.ORG_1]");
  });

  it("test_segment_bodies_carry_the_contract_text_but_never_a_placeholder", async () => {
    await renderForm();
    await load("A", BLOCKS, "a.docx");
    await reviewAndConfirm("A");
    for (const r of requests.filter((x) => x.url.includes("/api/segment"))) {
      expect(String(r.body)).not.toMatch(/\[[A-Z]\.[A-Z_]+_\d+\]/);
      expect(String(r.body)).not.toContain("a.docx");
    }
  });
});
