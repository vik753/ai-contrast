/** S7-T3 AC2 — "Delete all data in this browser" removes `aic.topics.v1` and the memory copy. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { must, stubTopicsFetch, topic } from "../test/topics-fakes";

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

it("test_clear_all_removes_saved_topics_and_memory", async () => {
  stubTopicsFetch();
  vi.resetModules();
  const i18n = await import("../i18n/index");
  await i18n.setupI18n();
  const { topicStore } = await import("./topicStore");
  topicStore.setPersist(true);
  topicStore.add(topic() as never);
  expect(localStorage.getItem("aic.topics.v1")).toContain("My topic");
  const mod: { default: ComponentType } = await import("../App");
  render(<mod.default />);
  await screen.findByRole("main");
  fireEvent.click(screen.getByRole("button", { name: /data and history/i }));
  fireEvent.click(await screen.findByRole("button", { name: /delete all data in this browser/i }));
  const dialogs = await screen
    .findAllByRole("dialog")
    .catch(() => screen.findAllByRole("alertdialog"));
  const dialog = must(dialogs[dialogs.length - 1]);
  const confirm = must(
    within(dialog)
      .getAllByRole("button")
      .find((b) => !/cancel/i.test(b.textContent)),
  );
  fireEvent.click(confirm);
  await waitFor(() => {
    expect(localStorage.getItem("aic.topics.v1")).toBeNull();
    expect(topicStore.getTopics()).toHaveLength(0);
  });
});
