import type { ChatterFlatAccountDTO } from "@/contexts/ChatterContext";
import type { SeedRow } from "@/lib/creatorFreshness";

export const chatterAccountsQuery = {
  queryKey: ["chatter", "self", "accounts"] as const,
  queryFn: async (): Promise<ChatterFlatAccountDTO[]> => {
    const r = await fetch("/chatter/me/accounts", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    // Throw, not []: a failed read is no answer, and the cache keeps the last list (useAccessChangeNotices diffs refetches).
    if (!r.ok) throw new Error(`/chatter/me/accounts ${r.status}`);
    return (await r.json()) as ChatterFlatAccountDTO[];
  },
};

export function chatterSeedRows(rows: readonly ChatterFlatAccountDTO[]): SeedRow[] {
  return rows.filter((r) => r.role !== "watcher").map((r) => ({ id: r.account_id, freshness: r.freshness }));
}
