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
 * The read is lib/splitInbox's, shared with its other readers.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import {
  splitInboxKey, splitInboxQueryOptions, type SplitInboxConfig, type SplitInboxResponse,
} from "@/lib/splitInbox";

export function useSplitInbox(accountId: string | null) {
  const qc = useQueryClient();
  const query = useQuery(splitInboxQueryOptions(accountId));
  const save = useMutation<SplitInboxResponse, Error, SplitInboxConfig>({
    mutationFn: (config) =>
      relay.put<SplitInboxResponse>(`/admin/split-inbox`, { account_id: accountId, config }),
    onSuccess: () => qc.invalidateQueries({ queryKey: splitInboxKey(accountId) }),
  });
  return { config: query.data?.config ?? null, query, save };
}
