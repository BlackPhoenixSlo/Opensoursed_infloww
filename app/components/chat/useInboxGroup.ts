"use client";

import { useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";

import type { OFChatItem } from "@/lib/relay";
import { inboxScope, splitInboxQueryOptions, type ScopeSplit, type SplitInboxResponse } from "@/lib/splitInbox";

const toSplits = (results: { data?: SplitInboxResponse; isError: boolean }[]): ScopeSplit[] =>
  results.map((r) => ({ config: r.data?.config ?? null, myGroup: r.data?.my_group ?? null, failed: r.isError }));

export function chatAccountOf(chat: OFChatItem, singleAccountId: string | null) {
  return chat.__accountId ?? singleAccountId;
}

export function useInboxGroup(accountIds: readonly string[], singleAccountId: string | null) {
  const splitList = useQueries({ queries: accountIds.map((id) => splitInboxQueryOptions(id)), combine: toSplits });
  const scopeKey = accountIds.join(",");
  const [selection, setSelection] = useState({ scopeKey, group: null as number | null });
  const picked = selection.scopeKey === scopeKey ? selection.group : null;
  const splits = useMemo(
    () => new Map(accountIds.map((id, i) => [id, splitList[i]] as const)),
    [accountIds, splitList],
  );
  const scope = useMemo(() => inboxScope(splits, picked), [splits, picked]);
  if (selection.scopeKey !== scopeKey || (scope.allLoaded && picked != null && picked > scope.groupCount)) {
    setSelection({ scopeKey, group: null });
  }
  const group = scope.locked ?? picked;
  const inGroup = useMemo(() => {
    const of = scope.of;
    if (!of) return null;
    return (c: OFChatItem) => {
      const accountId = chatAccountOf(c, singleAccountId);
      return accountId != null && of(accountId, c.withUser.id);
    };
  }, [scope, singleAccountId]);
  return {
    groupCount: scope.groupCount,
    group: inGroup ? group : null,
    setGroup: (group: number | null) => setSelection({ scopeKey, group }),
    inGroup,
    locked: scope.locked != null,
    pending: scope.pending,
    failed: scope.failed,
    wholeInbox: scope.allLoaded && accountIds.length > 0 && inGroup === null,
  };
}
