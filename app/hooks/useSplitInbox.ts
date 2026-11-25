"use client";


import { useMemo } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import {
  splitInboxKey, splitInboxQueryOptions, type SplitInboxConfig, type SplitInboxResponse,
} from "@/lib/splitInbox";

function putSplitInbox(accountId: string | null, config: SplitInboxConfig) {
  return relay.put<SplitInboxResponse>("/admin/split-inbox", { account_id: accountId, config });
}

export function useSplitInbox(accountId: string | null) {
  const qc = useQueryClient();
  const query = useQuery(splitInboxQueryOptions(accountId));
  const save = useMutation<SplitInboxResponse, Error, SplitInboxConfig>({
    mutationFn: (config) => putSplitInbox(accountId, config),
    onSuccess: () => qc.invalidateQueries({ queryKey: splitInboxKey(accountId) }),
  });
  return { config: query.data?.config ?? null, myGroup: query.data?.my_group ?? null, query, save };
}

const toStored = (results: { data?: SplitInboxResponse; error: Error | null }[]) => ({
  configs: results.map((r) => r.data?.config ?? null),
  error: results.find((r) => r.error && !r.data)?.error ?? null,
});

export function useSplitInboxes(accountIds: readonly string[], nameOf: (id: string) => string) {
  const qc = useQueryClient();
  const { configs, error } = useQueries({
    queries: accountIds.map((id) => splitInboxQueryOptions(id)), combine: toStored,
  });
  const stored = useMemo(
    () => (configs.every((c) => c) ? new Map(accountIds.map((id, i) => [id, configs[i]!] as const)) : null),
    [accountIds, configs],
  );
  const save = useMutation<void, Error, Map<string, SplitInboxConfig>>({
    mutationFn: async (payloads) => {
      const ids = [...payloads.keys()];
      const results = await Promise.allSettled([...payloads].map(([id, config]) => putSplitInbox(id, config)));
      const failed = results.flatMap((result, i) => result.status === "rejected"
        ? [{ id: ids[i], reason: result.reason as unknown }]
        : []);
      if (!failed.length) return;
      const saved = results.length - failed.length;
      const first = failed[0].reason;
      throw new Error(
        `Not saved for ${failed.map(({ id }) => nameOf(id)).join(", ")}` +
        `${first instanceof Error ? `: ${first.message}` : ""}.` +
        (saved ? ` ${saved} model${saved === 1 ? "" : "s"} saved.` : ""),
      );
    },
    onSettled: (_d, _e, payloads) =>
      Promise.all([...payloads.keys()].map((id) => qc.invalidateQueries({ queryKey: splitInboxKey(id) }))),
  });
  return { stored, error, save };
}
