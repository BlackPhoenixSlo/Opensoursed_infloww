"use client";


import { useCallback } from "react";
import { useMutation, useQueries, useQueryClient, type UseQueryResult } from "@tanstack/react-query";

import { relay } from "@/lib/relay";
import {
  splitInboxKey, splitInboxQueryOptions, type SplitInboxConfig, type SplitInboxEdits, type SplitInboxResponse,
  type SplitRead,
} from "@/lib/splitInbox";

export type SplitReadState = SplitRead & { fetching: boolean; failed: boolean };

function readOf(r: UseQueryResult<SplitInboxResponse>): SplitReadState {
  const myGroup = r.data?.my_group ?? null;
  const state = { myGroup, fetching: r.isFetching, failed: r.isError };
  const config = r.data?.config;
  if (config) return { status: "success", config, ...state };
  return { status: r.isError ? "error" : "pending", ...state };
}

export function useSplitInboxes(accountIds: readonly string[], { refetchOnMount }: { refetchOnMount?: "always" } = {}) {
  const qc = useQueryClient();
  const combine = useCallback(
    (results: UseQueryResult<SplitInboxResponse>[]): ReadonlyMap<string, SplitReadState> =>
      new Map(results.map((r, i) => [accountIds[i], readOf(r)])),
    [accountIds],
  );
  const splits = useQueries({
    queries: accountIds.map((id) => ({ ...splitInboxQueryOptions(id), ...(refetchOnMount && { refetchOnMount }) })),
    combine,
  });
  const save = useMutation<{ configs: Record<string, SplitInboxConfig> }, Error, SplitInboxEdits>({
    mutationFn: (edits) => relay.patch("/admin/split-inbox", edits),
    onSettled: (_d, _e, edits) =>
      Promise.all(edits.account_ids.map((id) => qc.invalidateQueries({ queryKey: splitInboxKey(id) }))),
  });
  return { splits, save };
}
