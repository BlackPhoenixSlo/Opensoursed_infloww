"use client";

import { useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";

import type { OFChatItem } from "@/lib/relay";
import { inboxScope, splitInboxQueryOptions, type ScopeSplit, type SplitInboxResponse } from "@/lib/splitInbox";

const toSplits = (results: { data?: SplitInboxResponse }[]): ScopeSplit[] =>
  results.map((r) => ({ config: r.data?.config ?? null, myGroup: r.data?.my_group ?? null }));

/**
 * The Split Inbox group chosen in the "All inboxes" selector over the
 * Creators in scope (one, or every Creator in All Models, where "Inbox N" is
 * group N of each Creator's own split). The choice is session state: a reload,
 * a change of Creators, or a count lowered below it returns to "All inboxes".
 *
 * `inGroup` filters loaded rows, null while no group applies. A chatter is
 * `locked` when every Creator in scope binds the same group (the relay
 * already serves only that group's Fans).
 */
export function useInboxGroup(accountIds: readonly string[]) {
  const splitList = useQueries({ queries: accountIds.map((id) => splitInboxQueryOptions(id)), combine: toSplits });
  const scopeKey = accountIds.join(",");
  const [picked, setPicked] = useState<number | null>(null);
  const [pickedFor, setPickedFor] = useState(scopeKey);
  if (pickedFor !== scopeKey) {
    setPickedFor(scopeKey);
    setPicked(null);
  }
  const splits = useMemo(
    () => new Map(accountIds.map((id, i) => [id, splitList[i]] as const)),
    [accountIds, splitList],
  );
  const scope = useMemo(() => inboxScope(splits, picked), [splits, picked]);
  const anyLoaded = splitList.some((s) => s.config);
  if (anyLoaded && picked != null && picked > scope.groupCount) setPicked(null);
  const group = scope.locked ?? picked;
  const single = accountIds.length === 1 ? accountIds[0] : "";
  const inGroup = useMemo(() => {
    const of = scope.of;
    if (!of) return null;
    return (c: OFChatItem) => of(c.__accountId ?? single, c.withUser.id);
  }, [scope, single]);
  return {
    groupCount: scope.groupCount,
    group: inGroup ? group : null,
    setGroup: setPicked,
    inGroup,
    locked: scope.locked != null,
    wholeInbox: scope.allLoaded && accountIds.length > 0 && inGroup === null,
  };
}
