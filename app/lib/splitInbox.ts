/**
 * splitInbox — a Creator's Split Inbox groups (account_ai_config.split_inbox_json,
 * ADR-0004), shared by Messages Pro (hooks/useSplitInbox, the Fan List's
 * "All inboxes" selector) and any queue that serves one group per Creator:
 * the stored shape, the group a Fan is in, the one query
 * (`["split-inbox", aid]`) every reader shares, and the per-group row filter.
 */

import { queryOptions } from "@tanstack/react-query";

import type { FanId } from "@/lib/fanId";
import { relay, type OFChatItem, type RelayContext } from "@/lib/relay";

/** The stored split: 1 to 9 groups, and only the explicit moves
 *  (Fan id → group); every other Fan's group is computed. */
export interface SplitInboxConfig {
  group_count: number;
  assignments: Record<string, number>;
}

export interface SplitInboxResponse {
  account_id: string;
  config: SplitInboxConfig;
}

/** The Split Inbox group (1 to N) a Fan belongs to: the Fan's explicit move
 *  when it is within range, otherwise a stable hash (32-bit FNV-1a) of the
 *  Fan id taken as text, modulo N, plus 1. Every Fan is in exactly one group,
 *  and a new split divides the Fans at once, the same way on every device
 *  (story 51). The id is never turned into a number, so a 19-digit id keeps
 *  its precision. */
export function groupOf(fanId: FanId, config: SplitInboxConfig): number {
  const n = config.group_count;
  const id = String(fanId);
  const moved = config.assignments[id];
  if (Number.isInteger(moved) && moved >= 1 && moved <= n) return moved;
  let hash = 0x811c9dc5;
  for (let i = 0; i < id.length; i++) {
    hash ^= id.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return ((hash >>> 0) % n) + 1;
}

const BG_CTX: RelayContext = { priority: "background" };

export const splitInboxKey = (accountId: string | null) => ["split-inbox", accountId] as const;

/** The read every view shares: a 60-second freshness window (the relay
 *  answers an unset Creator with one group and no moves). No Creator (null):
 *  disabled. */
export const splitInboxQueryOptions = (accountId: string | null) =>
  queryOptions({
    queryKey: splitInboxKey(accountId),
    enabled: accountId !== null,
    queryFn: () =>
      relay.get<SplitInboxResponse>(
        `/admin/split-inbox?account_id=${encodeURIComponent(accountId!)}`,
        BG_CTX,
      ),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

/** One Creator's split as a filtering reader sees it: still loading, its last read
 *  failed, or read. */
export type InboxSplit =
  | { status: "pending" }
  | { status: "error" }
  | { status: "success"; config: SplitInboxConfig };

export interface InboxFilter {
  /** The rows the reader may serve (`rows` itself when none was dropped). */
  rows: OFChatItem[];
  /** Per Creator: fan ids of its rows outside the picked group (all of them
   *  when the pick is above the split's count) — evidence those fans are gone
   *  from the queue. */
  out: ReadonlyMap<string, ReadonlySet<string>>;
  /** Split still loading: rows held back, the Creator not loaded yet. */
  pending: ReadonlySet<string>;
  /** Split read failed: rows held back, the Creator failed. */
  failed: ReadonlySet<string>;
}

/** The Split Inbox row filter: a row of a Creator in `picks` (Creator id →
 *  group, the Creators in play only) is kept only when its Fan's group is the
 *  pick (none when the pick is above the split's count: groupOf never
 *  answers it); never shown unfiltered (held back while the split loads or
 *  after a failed read). A Creator absent from `picks` (All inboxes) keeps every row. */
export function filterByInbox(
  rows: OFChatItem[],
  picks: Readonly<Record<string, number>>,
  splits: ReadonlyMap<string, InboxSplit>,
): InboxFilter {
  const pending = new Set<string>();
  const failed = new Set<string>();
  const configs = new Map<string, SplitInboxConfig>();
  for (const aid of Object.keys(picks)) {
    const split = splits.get(aid);
    if (!split || split.status === "pending") pending.add(aid);
    else if (split.status === "error") failed.add(aid);
    else configs.set(aid, split.config);
  }
  const out = new Map<string, Set<string>>();
  const kept = rows.filter((c) => {
    const aid = c.__accountId ?? "";
    if (!Object.hasOwn(picks, aid)) return true;
    if (pending.has(aid) || failed.has(aid)) return false;
    const config = configs.get(aid);
    if (config && groupOf(c.withUser.id, config) === picks[aid]) return true;
    let ids = out.get(aid);
    if (!ids) out.set(aid, (ids = new Set()));
    ids.add(String(c.withUser.id));
    return false;
  });
  return { rows: kept.length === rows.length ? rows : kept, out, pending, failed };
}
