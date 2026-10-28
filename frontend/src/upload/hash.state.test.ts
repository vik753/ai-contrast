/**
 * S4-T1 AC6 — `contractTextHash(contract)`.
 *
 * ASSUMPTIONS (the task does not fix them; the developer may adapt):
 * - exported from `src/upload/state.ts`, returns `Promise<string | null>`;
 * - an accepted file carries its text hash in the field `textHash`;
 * - result = sha256Hex(canonicalJson([textHash of each accepted row, in row order])).
 * Rejected rows are ignored. `null` while any row is `queued` or `checking`.
 */
import { describe, expect, it } from "vitest";
import { canonicalJson } from "../hash/key";
import { sha256Hex } from "../hash/sha256";
import * as stateModule from "./state";

type Fn = (contract: unknown) => Promise<string | null>;
const contractTextHash = (stateModule as Record<string, unknown>).contractTextHash as Fn;

const H1 = "1".repeat(64);
const H2 = "2".repeat(64);

function accepted(id: string, textHash: string): Record<string, unknown> {
  return {
    id,
    name: `${id}.pdf`,
    size: 10,
    status: "accepted",
    kind: "pdf",
    textHash,
    extraction: { language: "en", pages: 1, blocks: [], ocrPages: [], removed: [], warnings: [] },
  };
}

const contractOf = (...files: Record<string, unknown>[]): unknown => ({ id: "contract-1", files });

describe("contractTextHash", () => {
  it("test_contractTextHash_is_exported", () => {
    expect(typeof contractTextHash).toBe("function");
  });

  it("test_contractTextHash_accepted_rows_hash_canonical_json_of_ordered_text_hashes", async () => {
    const result = await contractTextHash(contractOf(accepted("a", H1), accepted("b", H2)));
    expect(result).toBe(await sha256Hex(canonicalJson([H1, H2])));
  });

  it("test_contractTextHash_row_order_changes_the_hash", async () => {
    const ab = await contractTextHash(contractOf(accepted("a", H1), accepted("b", H2)));
    const ba = await contractTextHash(contractOf(accepted("b", H2), accepted("a", H1)));
    expect(ab).not.toBe(ba);
  });

  it.each(["queued", "checking"])("test_contractTextHash_%s_row_gives_null", async (status) => {
    const pending = { id: "p", name: "p.pdf", size: 10, status };
    expect(await contractTextHash(contractOf(accepted("a", H1), pending))).toBeNull();
  });

  it("test_contractTextHash_rejected_row_is_ignored", async () => {
    const rejected = { id: "r", name: "r.pdf", size: 10, status: "rejected", code: "empty_file" };
    const result = await contractTextHash(contractOf(accepted("a", H1), rejected));
    expect(result).toBe(await sha256Hex(canonicalJson([H1])));
  });
});
