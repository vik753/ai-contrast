/** S8-T3 AC1 — the in-memory store of confirmed masked documents. */
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { maskedDoc } from "../test/tagging-fakes";
import { createMaskedDocsStore } from "./maskedDocsStore";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => vi.restoreAllMocks());

it("test_store_set_then_get_returns_documents_ordered_by_label", () => {
  const s = createMaskedDocsStore();
  s.set(maskedDoc("B"));
  s.set(maskedDoc("A"));
  expect(s.get().map((d) => d.label)).toEqual(["A", "B"]);
});

it("test_store_set_same_label_replaces_the_document", () => {
  const s = createMaskedDocsStore();
  s.set(maskedDoc("A", "a".repeat(64)));
  s.set(maskedDoc("A", "c".repeat(64)));
  expect(s.get()).toHaveLength(1);
  expect(s.get()[0]?.digest).toBe("c".repeat(64));
});

it("test_store_remove_drops_one_label", () => {
  const s = createMaskedDocsStore();
  s.set(maskedDoc("A"));
  s.set(maskedDoc("B"));
  s.remove("A");
  expect(s.get().map((d) => d.label)).toEqual(["B"]);
});

it("test_store_clear_all_empties_memory_and_notifies", () => {
  const s = createMaskedDocsStore();
  const fn = vi.fn();
  s.set(maskedDoc("A"));
  s.subscribe(fn);
  s.clearAll();
  expect(s.get()).toHaveLength(0);
  expect(fn).toHaveBeenCalled();
});

it("test_store_get_returns_same_array_when_nothing_changed", () => {
  const s = createMaskedDocsStore();
  s.set(maskedDoc("A"));
  expect(s.get()).toBe(s.get());
});

it("test_store_unsubscribe_stops_notifications", () => {
  const s = createMaskedDocsStore();
  const fn = vi.fn();
  const off = s.subscribe(fn);
  off();
  s.set(maskedDoc("A"));
  expect(fn).not.toHaveBeenCalled();
});

it("test_store_never_writes_local_session_storage_or_indexeddb", () => {
  const setItem = vi.spyOn(Storage.prototype, "setItem");
  const open = vi.fn();
  vi.stubGlobal("indexedDB", { open });
  const s = createMaskedDocsStore();
  s.set(maskedDoc("A"));
  s.remove("A");
  s.set(maskedDoc("B"));
  s.clearAll();
  expect(setItem).not.toHaveBeenCalled();
  expect(open).not.toHaveBeenCalled();
  expect(localStorage.length).toBe(0);
  expect(sessionStorage.length).toBe(0);
  vi.unstubAllGlobals();
});

it("test_clear_all_data_empties_the_singleton_store", async () => {
  const { maskedDocsStore } = await import("./maskedDocsStore");
  const { clearAllData } = await import("../storage/historySetting");
  maskedDocsStore.set(maskedDoc("A"));
  await clearAllData();
  expect(maskedDocsStore.get()).toHaveLength(0);
});
