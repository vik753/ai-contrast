/** S7-T3 review notes — Clear all, import confirmation, button names, in-flight guard. */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentType } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import en from "../i18n/locales/en.json";
import { flattenLocale } from "../test/locale-utils";
import { jsonResponse } from "../test/provider-fakes";
import { DOC, attr, bodyOf, must, stubTopicsFetch, topic } from "../test/topics-fakes";

const EN = flattenLocale(en);
const text = (k: string): string => String(EN[k]);

interface Props {
  connection: { provider: string; model?: string; key?: string };
  turnstileToken?: string;
  documents: ReturnType<typeof DOC>[];
}

async function setup(props: Partial<Props> = {}) {
  vi.resetModules();
  const i18n = await import("../i18n/index");
  await i18n.setupI18n();
  const mod = (await import("./TopicPanel")) as { TopicPanel: ComponentType<Props> };
  const store = await import("./topicStore");
  const keys = await import("../provider/keyStore");
  render(
    <mod.TopicPanel
      connection={{ provider: "anthropic", model: "m", key: "k" }}
      documents={[]}
      {...props}
    />,
  );
  await screen.findByRole("option", { name: "Car insurance" });
  return { store: store.topicStore, keys };
}
const pickDomain = () =>
  fireEvent.change(screen.getByLabelText(text("topics.domain.label")), {
    target: { value: "kasko" },
  });
const btn = (k: string) => screen.getByRole("button", { name: text(k) });

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("review notes", () => {
  it("test_clear_all_drops_the_held_free_pass", async () => {
    const { calls } = stubTopicsFetch((c) =>
      c.url === "/api/topics/propose-attributes"
        ? jsonResponse(200, { attributes: [attr()], dropped: 0, free_pass: "p1" })
        : undefined,
    );
    const { keys } = await setup({ connection: { provider: "free" }, turnstileToken: "tok" });
    pickDomain();
    fireEvent.change(screen.getByLabelText(text("topics.own.name")), { target: { value: "T" } });
    fireEvent.click(btn("topics.own.propose"));
    await screen.findByRole("list", { name: text("topics.attr.list") });
    act(() => {
      keys.notifyKeysCleared();
    });
    fireEvent.click(btn("topics.own.propose"));
    await waitFor(() => expect(calls.filter((c) => c.url.includes("propose"))).toHaveLength(2));
    const second = must(calls.filter((c) => c.url.includes("propose"))[1]);
    expect(second.headers.get("X-Free-Pass")).toBeNull();
    expect(bodyOf(second).turnstile_token).toBe("tok");
  });

  it("test_unknown_codes_use_the_unknown_message", async () => {
    stubTopicsFetch((c) =>
      c.url === "/api/topics/propose-attributes"
        ? jsonResponse(502, { error: "provider_unavailable" })
        : undefined,
    );
    await setup();
    pickDomain();
    fireEvent.change(screen.getByLabelText(text("topics.own.name")), { target: { value: "T" } });
    fireEvent.click(btn("topics.own.propose"));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(text("topics.error.unknown")),
    );
  });

  it("test_remove_buttons_have_distinct_names", async () => {
    stubTopicsFetch();
    const { store } = await setup();
    act(() => {
      store.add(topic({ topic_id: "custom_1", title: "One" }) as never);
      store.add(topic({ topic_id: "custom_2", title: "Two" }) as never);
    });
    expect(screen.getByRole("button", { name: "Remove topic: One" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove topic: Two" })).toBeTruthy();
  });

  it("test_export_is_disabled_without_topics", async () => {
    stubTopicsFetch();
    await setup();
    expect(btn("topics.export.button").hasAttribute("disabled")).toBe(true);
  });

  it("test_import_asks_before_replacing_own_topics", async () => {
    stubTopicsFetch();
    const { store } = await setup();
    act(() => {
      store.add(topic({ topic_id: "custom_1", title: "Keep me" }) as never);
    });
    const input = screen.getByLabelText<HTMLInputElement>(text("topics.import.label"));
    const file = new File(
      [JSON.stringify({ version: 1, topics: [topic({ title: "New one" })] })],
      "t.json",
    );
    fireEvent.change(input, { target: { files: [file] } });
    await screen.findByText(text("topics.import.replace"));
    expect(store.getTopics().map((x) => x.title)).toEqual(["Keep me"]);
    fireEvent.click(btn("topics.import.cancel"));
    expect(store.getTopics().map((x) => x.title)).toEqual(["Keep me"]);
    fireEvent.change(input, { target: { files: [file] } });
    await screen.findByText(text("topics.import.replace"));
    fireEvent.click(btn("topics.import.replaceYes"));
    expect(store.getTopics().map((x) => x.title)).toEqual(["New one"]);
  });

  it("test_confirm_blocks_new_calls_while_synonyms_are_expanding", async () => {
    let release: (r: Response) => void = () => undefined;
    stubTopicsFetch((c) => {
      if (c.url === "/api/topics/expand-synonyms")
        return new Promise<Response>((r) => {
          release = r;
        });
      return undefined;
    });
    await setup();
    pickDomain();
    fireEvent.change(screen.getByLabelText(text("topics.own.name")), { target: { value: "T" } });
    fireEvent.click(btn("topics.own.confirm"));
    fireEvent.change(screen.getByLabelText(text("topics.own.name")), { target: { value: "U" } });
    expect(btn("topics.own.propose").hasAttribute("disabled")).toBe(true);
    await act(async () => {
      release(jsonResponse(200, { synonyms_en: [], synonyms_uk: [], synonyms_ru: [], dropped: 0 }));
      await Promise.resolve();
    });
    await waitFor(() => expect(btn("topics.own.propose").hasAttribute("disabled")).toBe(false));
  });
});
