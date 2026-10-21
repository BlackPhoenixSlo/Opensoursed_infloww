"use client";

import { useMemo, useState } from "react";

import { chatRowKey } from "@/hooks/useChatList";
import type { OFChatItem } from "@/lib/relay";
import type { FocusModeSettings } from "./useFocusModeSettings";

/** The rows on screen when the list froze, the time of the newest message
 *  among them, and the list they were taken from. */
type Snapshot = { rows: OFChatItem[]; newestAt: number; listKey: string };

/** When a chat's newest message was sent; NaN for a chat with none, which
 *  compares false, so it never counts and never moves the mark. */
function lastMessageAt(c: OFChatItem): number {
  return c.lastMessage?.createdAt ? Date.parse(c.lastMessage.createdAt) : NaN;
}

function takeSnapshot(rows: OFChatItem[], listKey: string): Snapshot {
  let newestAt = -Infinity;
  for (const c of rows) {
    const at = lastMessageAt(c);
    if (at > newestAt) newestAt = at;
  }
  return { rows, newestAt, listKey };
}

/**
 * The Fan List's Focus mode (docs/spec/phase-02-fan-list-pane.md, Focus
 * mode). While it is on and `available`, the order and membership of the
 * rows on screen are frozen, and each row still shows its live contents.
 * The freeze is taken only from `settled` rows, so never from a cold load's
 * empty list, the local seed, or another list's placeholder rows; until the
 * list settles the live rows show. A new `listKey` (another Creator) drops
 * the snapshot and takes a new one once its rows settle, which clears the
 * count.
 * Only this view is frozen: the shared chats cache that `liveRows` comes from
 * keeps taking every realtime and head-poll write as they land.
 *
 * `newCount` is the number of chats in the live set whose newest message came
 * from the Fan after the freeze. `catchUp` (the banner's click) refreshes
 * through `refresh`; once that succeeds the list freezes again at the fresh
 * live order, which clears the count. A failed refresh keeps the frozen
 * order and the count. Session state, not persisted.
 *
 * `settings` (`useFocusModeSettings`) refine it while it is on and available:
 * without `pause` nothing freezes, and `hideMuted` drops muted chats from the
 * rows and the count.
 */
export function useFocusMode({
  liveRows: allLiveRows, listKey, settled, available, fromFan, refresh, settings,
}: {
  /** The rows the list would show without Focus mode, in order. */
  liveRows: OFChatItem[];
  /** The list `liveRows` belong to. A Creator change can answer from the
   *  cache without placeholder rows, so `settled` alone cannot signal it. */
  listKey: string;
  /** `liveRows` are this list's own answered rows: not the seed, not
   *  placeholder rows kept from another list, not a list still loading. */
  settled: boolean;
  /** Focus mode applies here (All, Newest first, no search); elsewhere it is
   *  suspended. */
  available: boolean;
  /** The chat's newest message came from the Fan. */
  fromFan: (c: OFChatItem) => boolean;
  /** Fetch the list past the relay cache, as the refresh icon does. */
  refresh: () => Promise<{ isError: boolean }>;
  settings: FocusModeSettings;
}) {
  const [focusMode, setFocusMode] = useState(false);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const on = focusMode && available;
  const frozen = on && settings.pause;
  const hideMuted = on && settings.hideMuted;
  const liveRows = useMemo(
    () => (hideMuted ? allLiveRows.filter((c) => !c.isMutedNotifications) : allLiveRows),
    [allLiveRows, hideMuted],
  );
  // The snapshot follows `frozen`, set while rendering so no frame shows the
  // live order once frozen: taken when the freeze starts (Focus mode on, back
  // in All with Newest first, or after a catch-up) and the rows have settled,
  // dropped when it stops or the list becomes another one. Turning the hide
  // on or off is another list too, so the rows freeze afresh.
  const viewKey = `${listKey}|${hideMuted}`;
  const stale = !!snapshot && (!frozen || snapshot.listKey !== viewKey);
  if (stale) setSnapshot(null);
  else if (frozen && settled && !snapshot) setSnapshot(takeSnapshot(liveRows, viewKey));
  const view = stale ? null : snapshot;

  const rows = useMemo(() => {
    if (!view) return liveRows;
    // Looked up in every live row, hidden or not, so a frozen row muted since
    // is seen as muted and leaves while the hide is on.
    const live = new Map(allLiveRows.map((c) => [chatRowKey(c), c]));
    // Membership is frozen too: a frozen row the live set has since dropped
    // keeps its last contents rather than leaving the screen.
    const kept = view.rows.map((c) => live.get(chatRowKey(c)) ?? c);
    return hideMuted ? kept.filter((c) => !c.isMutedNotifications) : kept;
  }, [view, liveRows, allLiveRows, hideMuted]);

  const newCount = useMemo(
    () => (view ? liveRows.filter((c) => fromFan(c) && lastMessageAt(c) > view.newestAt).length : 0),
    [view, liveRows, fromFan],
  );

  async function catchUp() {
    const result = await refresh();
    if (!result.isError) setSnapshot(null);
  }

  return { focusMode, setFocusMode, rows, newCount, catchUp };
}
