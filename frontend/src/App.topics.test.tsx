/** S7-T3 review — the topic panel is not mounted (no catalog request) before the button click. */
import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, expect, it, vi } from "vitest";
import en from "./i18n/locales/en.json";
import { flattenLocale } from "./test/locale-utils";
import { stubTopicsFetch } from "./test/topics-fakes";

afterEach(() => vi.unstubAllGlobals());

it("test_topic_panel_mounts_only_after_the_button_click", async () => {
  const { calls } = stubTopicsFetch();
  vi.resetModules();
  const i18n = await import("./i18n/index");
  await i18n.setupI18n();
  const mod: { default: ComponentType } = await import("./App");
  render(<mod.default />);
  await screen.findByRole("main");
  const label = String(flattenLocale(en)["topics.open"]);
  expect(
    screen.queryByRole("region", { name: String(flattenLocale(en)["topics.title"]) }),
  ).toBeNull();
  expect(calls.filter((c) => c.url.includes("/api/topics"))).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: label }));
  await screen.findByRole("region", { name: String(flattenLocale(en)["topics.title"]) });
});
