"use client";

import { useMemo, useState } from "react";

import { useSplitInboxes } from "@/hooks/useSplitInbox";
import { chatAccountOf } from "@/lib/chatsCache";
import type { OFChatItem } from "@/lib/relay";
import { inboxScope } from "@/lib/splitInbox";

export function useInboxGroup(accountIds: readonly string[]) {
  const { splits } = useSplitInboxes(accountIds);
  const scopeKey = accountIds.join(",");
  const [selection, setSelection] = useState({ scopeKey, group: null as number | null });
  const picked = selection.scopeKey === scopeKey ? selection.group : null;
  const scope = useMemo(() => inboxScope(splits, picked), [splits, picked]);
  if (selection.scopeKey !== scopeKey || (scope.allLoaded && picked != null && picked > scope.groupCount)) {
    setSelection({ scopeKey, group: null });
  }
  const group = scope.locked ?? picked;
  const single = accountIds.length === 1 ? accountIds[0] : null;
  const inGroup = useMemo(() => {
    const of = scope.of;
    if (!of) return null;
    return (c: OFChatItem) => {
      const accountId = chatAccountOf(c, single);
      return accountId != null && of(accountId, c.withUser.id);
    };
  }, [scope, single]);
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
