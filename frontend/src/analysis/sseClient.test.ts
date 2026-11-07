// @vitest-environment node
/** S9-T4 AC1 — strict SSE parser over a fetch body (ADR 0019 point 9). Fails until it exists. */
import { describe, expect, it } from "vitest";
import {
  controlled,
  enc,
  evDone,
  evOther,
  evStart,
  evTopic,
  finding,
  frame,
  streamOf,
} from "../test/analysis-fakes";
import { MAX_EVENT_BYTES, MAX_STREAM_BYTES, SseError, parseAnalysisStream } from "./sseClient";

type Caps = Parameters<typeof parseAnalysisStream>[1];
const MB = 1024 * 1024;

async function collect(chunks: (string | Uint8Array)[], caps?: Caps) {
  const out: { event: string; data: unknown }[] = [];
  for await (const e of parseAnalysisStream(streamOf(chunks), caps)) out.push(e);
  return out;
}
async function codeOf(chunks: (string | Uint8Array)[], caps?: Caps): Promise<unknown> {
  try {
    await collect(chunks, caps);
  } catch (e) {
    return e instanceof SseError ? e.code : e;
  }
  return "no error";
}

describe("parseAnalysisStream", () => {
  it("test_constants_follow_the_contract", () => {
    expect(MAX_EVENT_BYTES).toBe(65536);
    expect(MAX_STREAM_BYTES).toBeGreaterThanOrEqual(MB);
    expect(MAX_STREAM_BYTES).toBeLessThanOrEqual(16 * MB);
  });

  it("test_events_are_returned_in_order_with_parsed_data", async () => {
    const got = await collect([
      frame("start", evStart()),
      frame("topic", evTopic("deductible")),
      frame("other", evOther()),
      frame("progress", { done: 1, total: 2 }),
      frame("done", evDone()),
    ]);
    expect(got.map((e) => e.event)).toEqual(["start", "topic", "other", "progress", "done"]);
    expect(got[3]?.data).toEqual({ done: 1, total: 2 });
  });

  it("test_comment_heartbeats_are_ignored", async () => {
    const got = await collect([
      ": keep-alive\n\n",
      frame("start", evStart()),
      ": again\n\n",
      frame("done", evDone()),
    ]);
    expect(got.map((e) => e.event)).toEqual(["start", "done"]);
  });

  it("test_event_split_over_chunks_is_joined", async () => {
    const text = frame("start", evStart()) + frame("done", evDone());
    const chunks = text.split("").map((ch) => ch);
    const got = await collect(chunks);
    expect(got.map((e) => e.event)).toEqual(["start", "done"]);
  });

  it("test_utf8_character_split_over_chunks_is_decoded", async () => {
    const topic = frame(
      "topic",
      evTopic("deductible", { findings: [finding({ explanation: "\u0457\u0436\u0430\u043a" })] }),
    );
    const bytes = enc.encode(topic);
    const cut = bytes.indexOf(0xd1) + 1;
    const got = await collect([frame("start", evStart()), bytes.slice(0, cut), bytes.slice(cut)]);
    const t = got[1]?.data as { findings: { explanation: string }[] };
    expect(t.findings[0]?.explanation).toBe("\u0457\u0436\u0430\u043a");
  });

  it("test_unknown_event_name_is_an_error", async () => {
    expect(await codeOf([frame("start", evStart()), frame("surprise", {})])).toBe("unknown_event");
  });

  it("test_malformed_json_is_an_error", async () => {
    expect(await codeOf([frame("start", evStart()), "event: topic\ndata: {not json\n\n"])).toBe(
      "malformed_json",
    );
  });

  it.each([
    ["array", "[1]"],
    ["string", '"x"'],
    ["null", "null"],
  ])("test_data_that_is_%s_not_an_object_is_an_error", async (_n, raw) => {
    expect(await codeOf([frame("start", evStart()), `event: topic\ndata: ${raw}\n\n`])).toBe(
      "malformed_event",
    );
  });

  it("test_progress_with_wrong_types_is_an_error", async () => {
    expect(
      await codeOf([frame("start", evStart()), frame("progress", { done: "1", total: 2 })]),
    ).toBe("malformed_event");
  });

  it("test_topic_without_topic_id_is_an_error", async () => {
    const rest: Record<string, unknown> = { ...evTopic("x") };
    delete rest.topic_id;
    expect(await codeOf([frame("start", evStart()), frame("topic", rest)])).toBe("malformed_event");
  });

  it("test_done_without_a_hex64_result_signature_is_an_error", async () => {
    expect(
      await codeOf([frame("start", evStart()), frame("done", evDone({ result_signature: "xyz" }))]),
    ).toBe("malformed_event");
    const noSig: Record<string, unknown> = { ...evDone() };
    delete noSig.result_signature;
    expect(await codeOf([frame("start", evStart()), frame("done", noSig)])).toBe("malformed_event");
  });

  it("test_error_event_with_an_odd_code_is_an_error", async () => {
    expect(await codeOf([frame("start", evStart()), frame("error", { error: "<b>x</b>" })])).toBe(
      "malformed_event",
    );
  });

  it("test_two_data_lines_in_one_event_are_an_error", async () => {
    expect(await codeOf(["event: start\ndata: {}\ndata: {}\n\n"])).toBe("malformed_event");
  });

  it("test_event_after_done_is_an_error", async () => {
    expect(
      await codeOf([
        frame("start", evStart()),
        frame("done", evDone()),
        frame("progress", { done: 1, total: 1 }),
      ]),
    ).toBe("malformed_event");
  });

  it("test_first_event_must_be_start", async () => {
    expect(await codeOf([frame("topic", evTopic("deductible"))])).toBe("malformed_event");
  });

  it("test_event_over_the_cap_is_an_error", async () => {
    const big = frame("topic", evTopic("deductible", { values: ["x".repeat(500)] }));
    expect(await codeOf([frame("start", evStart()), big], { maxEventBytes: 200 })).toBe(
      "event_too_large",
    );
  });

  it("test_default_cap_refuses_an_event_of_65537_bytes", async () => {
    const pad = "x".repeat(MAX_EVENT_BYTES);
    expect(
      await codeOf([frame("start", evStart()), `event: topic\ndata: {"topic_id":"${pad}"}\n\n`]),
    ).toBe("event_too_large");
  });

  it("test_unterminated_block_is_cut_at_the_cap_without_waiting_for_the_end", async () => {
    const chunks = [frame("start", evStart()), "event: topic\ndata: " + "y".repeat(5000)];
    expect(await codeOf(chunks, { maxEventBytes: 1000 })).toBe("event_too_large");
  });

  it("test_total_stream_over_the_cap_is_an_error", async () => {
    const one = frame("progress", { done: 1, total: 9 });
    const chunks = [frame("start", evStart()), ...Array.from({ length: 20 }, () => one)];
    expect(await codeOf(chunks, { maxStreamBytes: 600 })).toBe("stream_too_large");
  });

  it("test_comment_bytes_count_toward_the_total_cap", async () => {
    const chunks = [
      frame("start", evStart()),
      ...Array.from({ length: 50 }, () => ": " + "z".repeat(40) + "\n\n"),
    ];
    expect(await codeOf(chunks, { maxStreamBytes: 1000 })).toBe("stream_too_large");
  });

  it("test_abort_cancels_the_reader_and_throws_abort_error", async () => {
    const live = controlled();
    const ac = new AbortController();
    const it = parseAnalysisStream(live.response.body, {
      signal: ac.signal,
    });
    live.push(frame("start", evStart()));
    const first = await it.next();
    expect(first.done).toBe(false);
    const pending = it.next();
    ac.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(live.cancelled()).toBe(true);
  });
});
