// Each page is a live OF request; bounds a repeatedly-clicked surface.
export const ANCHOR_MAX_PAGES = 6;

export type AnchorStep = "jump" | "wait" | "loadOlder" | "giveUp";

export function anchorNext({ loading, found, pages, hasOlder, loadingOlder }: {
  loading: boolean; found: boolean; pages: number; hasOlder: boolean; loadingOlder: boolean;
}): AnchorStep {
  if (loading) return "wait";
  if (found) return "jump";
  if (!hasOlder || loadingOlder) return "wait";
  return pages >= ANCHOR_MAX_PAGES ? "giveUp" : "loadOlder";
}

export function newBackfillKeys(seen: ReadonlySet<string>, keys: readonly string[]): string[] {
  const out: string[] = [];
  const taken = new Set<string>();
  for (const key of keys) {
    if (seen.has(key) || taken.has(key)) continue;
    taken.add(key);
    out.push(key);
  }
  return out;
}
