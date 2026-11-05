/** Helpers for S7-T3 tests: a synthetic catalog and a routing fake fetch. */
import { vi } from "vitest";
import { jsonResponse, type Captured } from "./provider-fakes";

const L = (en: string, uk: string, ru: string) => ({ en, uk, ru });

export const CATALOG = {
  catalog_version: "v-test-1",
  domains: [
    {
      id: "kasko",
      names: L("Car insurance", "Автострахування", "Автострахование"),
      sides: [
        { id: "insured", names: L("Insured", "Страхувальник", "Страхователь") },
        { id: "insurer", names: L("Insurer", "Страховик", "Страховщик") },
      ],
      topics: [
        {
          id: "deductible",
          names: L("Deductible", "Франшиза", "Франшиза"),
          descriptions: L("What you pay.", "Що ви платите.", "Что вы платите."),
          synonyms: { en: ["deductible"], uk: ["франшиз"], ru: ["франшиз"] },
          attributes: [
            {
              id: "amount",
              labels: L("Deductible amount", "Розмір франшизи", "Размер франшизы"),
              type: "amount",
              units: ["UAH", "percent_of_sum"],
              directions: { insured: "lower_better", insurer: "higher_better" },
            },
          ],
        },
        {
          id: "theft",
          names: L("Theft cover", "Покриття крадіжки", "Покрытие кражи"),
          descriptions: L("Theft.", "Крадіжка.", "Кража."),
          synonyms: { en: ["theft"], uk: ["крадіж"], ru: ["кража"] },
          attributes: [
            {
              id: "covered",
              labels: L("Covered", "Покрито", "Покрыто"),
              type: "enum",
              values: [
                { id: "covered", labels: L("Yes", "Так", "Да") },
                { id: "not_covered", labels: L("No", "Ні", "Нет") },
              ],
              directions: { insured: ["covered", "not_covered"], insurer: "none" },
            },
          ],
        },
      ],
    },
    {
      id: "lease",
      names: L("Lease", "Оренда", "Аренда"),
      sides: [
        { id: "tenant", names: L("Tenant", "Орендар", "Арендатор") },
        { id: "landlord", names: L("Landlord", "Орендодавець", "Арендодатель") },
      ],
      topics: [
        {
          id: "rent",
          names: L("Rent", "Орендна плата", "Арендная плата"),
          descriptions: L("Rent.", "Плата.", "Плата."),
          synonyms: { en: ["rent"], uk: ["плат"], ru: ["плат"] },
          attributes: [
            {
              id: "monthly",
              labels: L("Monthly rent", "Щомісячна плата", "Ежемесячная плата"),
              type: "amount",
              units: ["UAH"],
              directions: { tenant: "lower_better", landlord: "higher_better" },
            },
          ],
        },
      ],
    },
  ],
};

export type Reply = Response | Promise<Response>;
export type Router = (c: Captured) => Reply | undefined;

/** Routes by URL path. Unrouted `/api/topics/catalog` returns CATALOG. Records every call. */
export function stubTopicsFetch(route: Router = () => undefined): { calls: Captured[] } {
  const calls: Captured[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const i = init ?? {};
      const c: Captured = {
        url: typeof input === "string" ? input : input instanceof URL ? input.href : input.url,
        method: i.method,
        headers: new Headers(i.headers),
        body: typeof i.body === "string" ? i.body : undefined,
        init: i,
      };
      calls.push(c);
      const r = route(c);
      if (r) return Promise.resolve(r);
      if (c.url === "/api/topics/catalog") return Promise.resolve(jsonResponse(200, CATALOG));
      return Promise.resolve(jsonResponse(500, { error: "unknown" }));
    }),
  );
  return { calls };
}

export const bodyOf = (c: Captured): Record<string, unknown> =>
  JSON.parse(c.body ?? "{}") as Record<string, unknown>;

export function attr(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "a1",
    label: "Limit",
    type: "amount",
    units: ["UAH"],
    direction: "none",
    order: [],
    values: [],
    direction_source: "client",
    ...over,
  };
}

export function topic(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    origin: "custom",
    domain: "kasko",
    topic_id: "custom_1",
    title: "My topic",
    description: "Mine",
    side: "insured",
    attributes: [attr()],
    synonyms_en: [],
    synonyms_uk: [],
    synonyms_ru: [],
    ...over,
  };
}

export const DOC = (label: string) => ({
  label,
  detectorVersion: "pseudo-1",
  clauses: [{ id: "c1", text: "1. Text" }],
  acknowledgedUnmasked: [] as [string, number, number][],
});
