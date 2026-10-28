/**
 * Test helpers for S5-T2 (clauses in the browser): wire-format builders for
 * `POST /api/segment` replies and a fetch router with one fake per endpoint.
 * Everything is synthetic; no real network call is made.
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import i18next from "i18next";
import type { ComponentType } from "react";
import { createElement } from "react";
import { I18nextProvider } from "react-i18next";
import { expect, vi } from "vitest";
import { setupI18n } from "../i18n";
import * as UploadFormModule from "../upload/UploadForm";
import { FakeFetch, fileList, jsonResponse, okResponse } from "./upload-fakes";

export const SEGMENT_URL = "/api/segment";

export interface WireBlock {
  text: string;
  part: string;
  page: number | null;
}
export type WireSpan = [number, number, number];
export interface WireClause {
  id: string;
  number: string | null;
  level: number;
  part_index: number;
  section_kind: "requisites" | null;
  part: string;
  pages: number[];
  spans: WireSpan[];
  heading_span: WireSpan | null;
}

export const body = (text: string, page: number | null = null): WireBlock => ({
  text,
  part: "body",
  page,
});

export function clause(index: number, overrides: Partial<WireClause> = {}): WireClause {
  return {
    id: `c${String(index)}`,
    number: null,
    level: 1,
    part_index: 0,
    section_kind: null,
    part: "body",
    pages: [],
    spans: [],
    heading_span: null,
    ...overrides,
  };
}

/** A valid reply with one clause per block, covering it completely. */
export function segmentReply(
  blocks: readonly WireBlock[],
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    clauses: blocks.map((block, index) =>
      clause(index + 1, {
        part: block.part === "body" ? "body" : block.part,
        spans: [[index, 0, block.text.length]],
        pages: block.page === null ? [] : [block.page],
      }),
    ),
    blocks,
    removed: [],
    warnings: [],
    detector_version: "det-test",
    entities: [],
    requisites: [],
    neutralized: [],
    ...overrides,
  };
}

export const segmentOk = (blocks: readonly WireBlock[], overrides = {}): Response =>
  jsonResponse(200, segmentReply(blocks, overrides));

/** The blocks of a request body sent to `/api/segment` (a JSON string). */
export function requestBlocks(call: { body: unknown }): WireBlock[] {
  const parsed = JSON.parse(String(call.body)) as { blocks: WireBlock[] };
  return parsed.blocks;
}

export class Servers {
  readonly extract = new FakeFetch();
  readonly segment = new FakeFetch();
  /** Extraction blocks per added file (default: one body block). */
  readonly extractBlocks = new Map<Blob, WireBlock[]>();
  readonly extractOverrides = new Map<Blob, Record<string, unknown>>();

  constructor() {
    this.extract.autoRespond = (payload) => {
      const blob = payload as Blob;
      const blocks = this.extractBlocks.get(blob) ?? [body("Synthetic clause one.")];
      const overrides = this.extractOverrides.get(blob);
      // A reply with `pages` is a PDF; the strict client rejects "docx" with pages.
      return okResponse(overrides?.pages === undefined ? "docx" : "pdf", blob.size, {
        blocks,
        ...overrides,
      });
    };
  }

  /** Every segment request is answered with a valid reply echoing its blocks. */
  segmentAutomatically(): void {
    this.segment.autoRespond = (payload) =>
      segmentOk((JSON.parse(String(payload)) as { blocks: WireBlock[] }).blocks);
  }

  install(): void {
    vi.stubGlobal("fetch", (input: unknown, init?: RequestInit) =>
      String(input).includes(SEGMENT_URL)
        ? this.segment.fetch(input, init)
        : this.extract.fetch(input, init),
    );
  }
}

const moduleExports: Record<string, unknown> = UploadFormModule;
const UploadForm = (moduleExports.UploadForm ?? moduleExports.default) as ComponentType;

export async function renderForm(): Promise<() => void> {
  await setupI18n();
  const { unmount } = render(
    createElement(I18nextProvider, { i18n: i18next }, createElement(UploadForm)),
  );
  await screen.findByRole("region", { name: "Contract A" });
  return unmount;
}

export const region = (label: string): HTMLElement =>
  screen.getByRole("region", { name: `Contract ${label}` });

export function addFile(servers: Servers, label: string, file: File, blocks?: WireBlock[]): File {
  if (blocks !== undefined) {
    servers.extractBlocks.set(file, blocks);
  }
  const input = region(label).querySelector<HTMLInputElement>('input[type="file"]');
  if (input === null) {
    throw new Error("No file input");
  }
  act(() => {
    fireEvent.change(input, { target: { files: fileList([file]) } });
  });
  return file;
}

export function row(label: string, name: string): HTMLElement {
  const item = within(region(label))
    .queryAllByRole("listitem")
    .find((li) => li.textContent.includes(name));
  if (item === undefined) {
    throw new Error(`No row containing ${name} in Contract ${label}`);
  }
  return item;
}

export const rowText = (label: string, name: string): string => row(label, name).textContent;

export async function waitSegmentCalls(servers: Servers, count: number): Promise<void> {
  await waitFor(() => {
    expect(servers.segment.calls.length).toBe(count);
  });
}

export const settle = (ms = 40): Promise<void> =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });

export function removeFile(label: string): void {
  act(() => {
    fireEvent.click(within(region(label)).getByRole("button", { name: /^remove (?!contract)/i }));
  });
}
