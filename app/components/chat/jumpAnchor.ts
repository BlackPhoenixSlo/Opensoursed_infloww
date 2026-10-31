/**
 * Pure decisions behind ChatSurface's ?msg= jump (useJumpToMessage) and its
 * vault-sends backfill dedupe. No React, no I/O.
 */

// How many pages of history the ?msg= anchor may pull. Each one is a live
// OnlyFans request, so this bounds a repeatedly-clicked surface to a handful of
// upstream calls rather than "page until found".
export const ANCHOR_MAX_PAGES = 6;

/** What the anchor effect does next: jump to the rendered target, wait for
 *  the next render (the thread or an older page still loading, or none to
 *  pull), pull one more page, or give up quietly and stay put. */
export type AnchorStep = "jump" | "wait" | "loadOlder" | "giveUp";

/** `pages` is how many older pages this anchor has already pulled. */
export function anchorNext({ loading, found, pages, hasOlder, loadingOlder }: {
  loading: boolean; found: boolean; pages: number; hasOlder: boolean; loadingOlder: boolean;
}): AnchorStep {
  if (loading) return "wait";
  if (found) return "jump";
  if (!hasOlder || loadingOlder) return "wait";
  return pages >= ANCHOR_MAX_PAGES ? "giveUp" : "loadOlder";
}

/** The message ids not yet backfilled, in order, each once. Keyed as TEXT: a
 *  Fansly message id is a snowflake past 2^53. Does not mutate `seen`. */
export function newBackfillIds(seen: ReadonlySet<string>, ids: readonly string[]): string[] {
  const out: string[] = [];
  const taken = new Set<string>();
  for (const id of ids) {
    if (seen.has(id) || taken.has(id)) continue;
    taken.add(id);
    out.push(id);
  }
  return out;
}
