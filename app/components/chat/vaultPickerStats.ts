/**
 * The Vault picker's per-media sales stats (Infloww's Sent count, Unlock
 * count, Unlock rate), the sorts over them and "Recently used", and the
 * "Hide content viewed or unlocked by fan, or posted on Creator's feed"
 * rule. Pure; kept out of VaultPicker.tsx, which is already over size.
 */

import type { VaultMediaStat } from "@/hooks/useVaultMediaStats";

/** The sorts our stats drive. "newest" / "oldest" stay OF's (server-side). */
export const STATS_SORTS = [
  { value: "sent", label: "Send count" },
  { value: "unlocks", label: "Unlock count" },
  { value: "unlock_rate", label: "Unlock rate" },
  { value: "recent", label: "Recently used" },
] as const;
export type StatsSort = (typeof STATS_SORTS)[number]["value"];

export function isStatsSort(v: unknown): v is StatsSort {
  return STATS_SORTS.some((s) => s.value === v);
}

/** Order the loaded media by a stats sort, best first. Stable: media with no
 *  stats (never sent) keep the order OF served them in, after the rest. */
export function sortByStats<T extends { id: number }>(
  items: T[], byMedia: Record<string, VaultMediaStat>, sort: StatsSort,
): T[] {
  const key = (st: VaultMediaStat): number[] => {
    switch (sort) {
      case "sent": return [st.sent, st.unlocks];
      case "unlocks": return [st.unlocks, st.unlock_rate ?? -1];
      case "unlock_rate": return [st.unlock_rate ?? -1, st.unlocks];
      case "recent": return [st.last_sent_at ? Date.parse(st.last_sent_at) : -1];
    }
  };
  const ranked = items.map((m, i) => ({ m, i, k: byMedia[String(m.id)] ? key(byMedia[String(m.id)]) : null }));
  ranked.sort((a, b) => {
    if (!a.k || !b.k) return a.k ? -1 : b.k ? 1 : a.i - b.i;
    for (let j = 0; j < a.k.length; j++) if (a.k[j] !== b.k[j]) return b.k[j] - a.k[j];
    return a.i - b.i;
  });
  return ranked.map((r) => r.m);
}

/** "Sent 12 · Unlock 3 · 25%": the rate only when it was ever sent priced. */
export function statsLabel(st: VaultMediaStat): string {
  const rate = st.unlock_rate == null ? "" : ` · ${Math.round(st.unlock_rate * 100)}%`;
  return `Sent ${st.sent} · Unlock ${st.unlocks}${rate}`;
}

/** Viewed or unlocked by the Fan (bought, or sent free), or on the Creator's
 *  feed: what "Hide content viewed or unlocked…" removes. A PPV he left
 *  locked stays. */
export function seenByFan(status: string | null): boolean {
  return status === "unlocked" || status === "free" || status === "on-wall";
}
