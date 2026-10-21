"use client";

import { useMemo, useState } from "react";

import { useSplitInbox } from "@/hooks/useSplitInbox";
import type { OFChatItem } from "@/lib/relay";
import { groupOf } from "./SplitInbox";

/**
 * The Split Inbox group chosen in the "All inboxes" selector
 * (docs/spec/phase-02-fan-list-pane.md, Split Inbox; story 9). It reads the
 * Creator's split (`useSplitInbox`, 60-second freshness) and keeps the chosen
 * group as session state: a reload, or a change of Creator, returns to "All
 * inboxes", because a group number belongs to one Creator's split. So does a
 * saved split that lowers the count below the chosen group: the choice itself
 * resets, so raising the count again does not bring the old group back. All
 * Models (no Creator) has no split.
 *
 * `inGroup` is the client-side filter over loaded rows, and null while "All
 * inboxes" is chosen: the one place that decides whether a group applies.
 */
export function useInboxGroup(accountId: string | null) {
  const { config } = useSplitInbox(accountId);
  const [picked, setPicked] = useState<number | null>(null);
  const [pickedFor, setPickedFor] = useState(accountId);
  if (pickedFor !== accountId) {
    setPickedFor(accountId);
    setPicked(null);
  }
  if (config && picked != null && picked > config.group_count) setPicked(null);
  const inGroup = useMemo(() => {
    if (!config || picked == null) return null;
    return (c: OFChatItem) => groupOf(c.withUser.id, config) === picked;
  }, [config, picked]);
  return {
    groupCount: config?.group_count ?? 1,
    group: inGroup ? picked : null,
    setGroup: setPicked,
    inGroup,
  };
}
