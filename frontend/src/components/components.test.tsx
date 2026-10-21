/**
 * Unit tests for shell components (frontend-dev).
 */
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "../App";
import { isLanguage, setupI18n } from "../i18n";
import enJson from "../i18n/locales/en.json";
import { resetBrowserEnv } from "../test/browser-env";
import { flattenLocale, text } from "../test/locale-utils";
import { RatingIcon, type Rating } from "./RatingIcon";

const EN = flattenLocale(enJson);

beforeEach(() => {
  resetBrowserEnv();
});

afterEach(() => {
  resetBrowserEnv();
});

describe("isLanguage", () => {
  it.each(["en", "uk", "ru"])("accepts %s", (value) => {
    expect(isLanguage(value)).toBe(true);
  });

  it.each(["", "EN", "de", "uk-UA", null, undefined, 1, {}])("rejects %j", (value) => {
    expect(isLanguage(value)).toBe(false);
  });
});

describe("RatingIcon", () => {
  it.each<Rating>(["green", "yellow", "red"])("is hidden from assistive technology (%s)", (r) => {
    const { container } = render(<RatingIcon rating={r} />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("aria-hidden")).toBe("true");
    expect(svg?.getAttribute("focusable")).toBe("false");
  });

  it("uses a different shape for every rating", () => {
    const shapes = (["green", "yellow", "red"] as const).map((r) => {
      const { container } = render(<RatingIcon rating={r} />);
      return Array.from(container.querySelectorAll("path"))
        .map((p) => p.getAttribute("d"))
        .join("|");
    });
    expect(new Set(shapes).size).toBe(3);
  });
});

describe("App shell", () => {
  it("pairs every rating icon with a visible text label", async () => {
    await setupI18n();
    render(<App />);
    // S2-T2: the upload form adds more lists; use the one in the ratings card.
    const ratingsCard = screen.getByRole("region", { name: text(EN, "home.ratings.title") });
    const list = within(ratingsCard).getByRole("list");
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    for (const item of items) {
      expect(item.querySelector("svg[aria-hidden='true']")).not.toBeNull();
      expect(item.querySelector("strong")?.textContent.trim() ?? "").not.toBe("");
    }
  });

  it("has exactly one h1", async () => {
    await setupI18n();
    render(<App />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("language buttons are real buttons that do not submit forms", async () => {
    await setupI18n();
    render(<App />);
    for (const button of screen.getAllByRole("button")) {
      expect(button.getAttribute("type")).toBe("button");
    }
  });
});
