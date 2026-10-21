/**
 * /chatter/me/accounts: one key and fetch for ChatterContext and useAccounts,
 * so both read the same cache entry. Its own module rather than an export of
 * ChatterContext, which most tests mock whole.
 */

import type { ChatterFlatAccountDTO } from "@/contexts/ChatterContext";

export const chatterAccountsQuery = {
  queryKey: ["chatter", "self", "accounts"] as const,
  queryFn: async (): Promise<ChatterFlatAccountDTO[]> => {
    const r = await fetch("/chatter/me/accounts", {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    // Throw, not []: a failed read is no answer, and the cache keeps the last
    // list (useAccessChangeNotices diffs refetches).
    if (!r.ok) throw new Error(`/chatter/me/accounts ${r.status}`);
    return (await r.json()) as ChatterFlatAccountDTO[];
  },
};
