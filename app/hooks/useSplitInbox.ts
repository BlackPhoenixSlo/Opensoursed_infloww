"use client";

/**
 * useSplitInbox — read/write a Creator's Split Inbox groups
 * (account_ai_config.split_inbox_json, ADR-0004) through
 * `GET`/`PUT /admin/split-inbox`.
 *
 * Follows useNudgeConfig (docs/spec/phase-02-fan-list-pane.md, Split Inbox):
 * a 60-second freshness window and invalidation on save. Other Employees and
 * devices see a save on their next fetch; nothing is pushed. The relay answers
 * an unset Creator with one group and no moves, and refuses a chatter's save.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay, type RelayContext } from "@/lib/relay";

const KEY = "split-inbox";
const BG_CTX: RelayContext = { priority: "background" };

/** The stored split: 1 to 9 groups, and only the explicit moves
 *  (Fan id → group); every other Fan's group is computed. */
export interface SplitInboxConfig {
  group_count: number;
  assignments: Record<string, number>;
}

interface SplitInboxResponse {
  account_id: string;
  config: SplitInboxConfig;
}

export function useSplitInbox(accountId: string | null) {
  const qc = useQueryClient();
  const query = useQuery<SplitInboxResponse>({
    queryKey: [KEY, accountId],
    enabled: !!accountId,
    queryFn: () =>
      relay.get<SplitInboxResponse>(
        `/admin/split-inbox?account_id=${encodeURIComponent(accountId!)}`,
        BG_CTX,
      ),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const save = useMutation<SplitInboxResponse, Error, SplitInboxConfig>({
    mutationFn: (config) =>
      relay.put<SplitInboxResponse>(`/admin/split-inbox`, { account_id: accountId, config }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [KEY, accountId] }),
  });
  return { config: query.data?.config ?? null, query, save };
}
