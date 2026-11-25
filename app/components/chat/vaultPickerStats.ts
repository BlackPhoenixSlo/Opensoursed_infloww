import type { VaultMediaStat } from "@/hooks/useVaultMediaStats";

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

export function statsLabel(st: VaultMediaStat): string {
  const rate = st.unlock_rate == null ? "" : ` · ${Math.round(st.unlock_rate * 100)}%`;
  return `Sent ${st.sent} · Unlock ${st.unlocks}${rate}`;
}

// What "Hide content viewed or unlocked" removes (bought, free, or on the feed); a PPV left locked stays.
export function seenByFan(status: string | null): boolean {
  return status === "unlocked" || status === "free" || status === "on-wall";
}
