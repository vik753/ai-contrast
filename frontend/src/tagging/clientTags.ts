/** Rules for client-added tags (ADR 0018 point 5). Add only; the caps are enforced here, not only by the UI. */
import type { TagReply } from "./tagApi";

export const MAX_CLIENT_PER_TOPIC = 120;
export const MAX_NON_KEYWORD_PER_CLAUSE = 5;

/**
 * The new client tags of `clauseId`, or `null` when the change is refused. Removing is always
 * allowed. A new tag needs a selected topic id, a clause of the document, no existing tag of that
 * topic on the clause, at most 5 non-keyword tags on the clause and at most 120 clauses per topic
 * (keyword clauses plus client tags).
 */
export function setClientTags(
  reply: TagReply,
  current: Readonly<Record<string, readonly string[]>>,
  clauseId: string,
  next: readonly string[],
  allowed: ReadonlySet<string>,
  clauseIds: ReadonlySet<string>,
): Record<string, string[]> | null {
  if (!clauseIds.has(clauseId)) return null;
  const unique = [...new Set(next)];
  const before = new Set(current[clauseId] ?? []);
  const added = unique.filter((id) => !before.has(id));
  const out: Record<string, string[]> = {};
  for (const [k, v] of Object.entries(current)) if (k !== clauseId) out[k] = [...v];
  if (added.length > 0) {
    const tags = reply.tags[clauseId] ?? [];
    const nonKeyword = tags.filter((t) => t.source !== "keyword").length;
    if (nonKeyword + unique.length > MAX_NON_KEYWORD_PER_CLAUSE) return null;
    for (const id of added) {
      if (!allowed.has(id) || tags.some((t) => t.topic_id === id)) return null;
      const others = Object.entries(out).filter(
        ([k, v]) => clauseIds.has(k) && v.includes(id),
      ).length;
      if ((reply.topics[id]?.keyword_clauses ?? 0) + others + 1 > MAX_CLIENT_PER_TOPIC) return null;
    }
  }
  if (unique.length > 0) out[clauseId] = unique;
  return out;
}
