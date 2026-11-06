/** Cost estimate and model pair shown before tagging (S8-T3). The numbers are estimates only. */
import type { SafetyDocument } from "../api/safetyCheck";

export const FREE_MODEL = "@cf/openai/gpt-oss-120b";

const BATCH_CHARS = 12_000;
const BATCH_CLAUSES = 40;
const BATCH_OVERHEAD_TOKENS = 200;
const TOPIC_TOKENS = 60;

export interface Estimate {
  calls: number;
  maxCheckCalls: number;
  inputTokens: number;
}

export function estimateTagging(docs: readonly SafetyDocument[], topicCount: number): Estimate {
  let calls = 0;
  let inputTokens = 0;
  for (const doc of docs) {
    const chars = doc.clauses.reduce((n, c) => n + Array.from(c.text).length, 0);
    const batches =
      chars === 0
        ? 0
        : Math.max(Math.ceil(chars / BATCH_CHARS), Math.ceil(doc.clauses.length / BATCH_CLAUSES));
    calls += batches;
    inputTokens +=
      Math.ceil(chars / 3) + batches * (BATCH_OVERHEAD_TOKENS + TOPIC_TOKENS * topicCount);
  }
  return { calls, maxCheckCalls: calls, inputTokens };
}

export function modelPairOf(c: { provider: string; model?: string; checkModel?: string }): {
  cheap: string;
  strong: string;
} {
  if (c.provider === "free") return { cheap: FREE_MODEL, strong: FREE_MODEL };
  const cheap = c.model ?? "";
  return { cheap, strong: c.checkModel ?? cheap };
}
