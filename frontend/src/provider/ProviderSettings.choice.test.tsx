/** S7-T3 review — `onChoiceChange` reports again after a key change. */
import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentType } from "react";
import { expect, it, vi } from "vitest";

it("test_onChoiceChange_re_reports_after_a_key_change", async () => {
  vi.resetModules();
  const i18n = await import("../i18n/index");
  await i18n.setupI18n();
  const mod = (await import("./ProviderSettings")) as {
    ProviderSettings: ComponentType<{ onChoiceChange: (c: { provider: string }) => void }>;
  };
  const spy = vi.fn();
  render(<mod.ProviderSettings onChoiceChange={spy} />);
  fireEvent.change(screen.getByLabelText<HTMLSelectElement>(/^provider$/i), {
    target: { value: "openai" },
  });
  const before = spy.mock.calls.length;
  fireEvent.change(screen.getByLabelText(/api key/i), { target: { value: "sk-test-1" } });
  expect(spy.mock.calls.length).toBeGreaterThan(before);
  expect(JSON.stringify(spy.mock.calls)).not.toContain("sk-test-1");
});
