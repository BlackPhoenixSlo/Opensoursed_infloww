/**
 * splitInbox — a Creator's Split Inbox groups (account_ai_config.split_inbox_json,
 * ADR-0004), shared by Messages Pro (hooks/useSplitInbox, the Fan List's
 * "All inboxes" selector) and any queue that serves one group per Creator:
 * the stored shape, the group a Fan is in, the one query
 * (`["split-inbox", aid]`) every reader shares, and the per-group gate.
 */

import { queryOptions } from "@tanstack/react-query";

import type { FanId } from "@/lib/fanId";
import { relay, type RelayContext } from "@/lib/relay";

/** The stored split: 1 to 9 groups, the explicit moves (Fan id → group) and
 *  the owner's chatter bindings (chatter id → group; absent = sees every group).
 *  A chatter's read carries no `chatter_groups`. */
export interface SplitInboxConfig {
  group_count: number;
  assignments: Record<string, number>;
  chatter_groups?: Record<string, number>;
}

export interface SplitInboxResponse {
  account_id: string;
  config: SplitInboxConfig;
  /** The signed-in chatter's bound group; the relay serves it only that
   *  group's Fans. Null for an owner or an unbound chatter. */
  my_group?: number | null;
}

/** The Split Inbox group (1 to N) a Fan belongs to: the Fan's explicit move
 *  when it is within range, else the Fan id mod N plus 1, as the relay's
 *  split_inbox.group_of (it filters a bound chatter's Fans by the same rule).
 *  The mod is taken over the digit string, so a 19-digit id keeps its
 *  precision; a non-numeric id is in group 1. */
export function groupOf(fanId: FanId, config: SplitInboxConfig): number {
  const n = config.group_count;
  const id = String(fanId);
  const moved = config.assignments[id];
  if (Number.isInteger(moved) && moved >= 1 && moved <= n) return moved;
  if (!/^[0-9]+$/.test(id)) return 1;
  let r = 0;
  for (let i = 0; i < id.length; i++) r = (r * 10 + id.charCodeAt(i) - 48) % n;
  return r + 1;
}

/** The group a bound chatter is locked to, or null (an owner, an unbound
 *  chatter, or a binding the current count no longer reaches). */
export function lockedGroup(config: SplitInboxConfig | null, myGroup: number | null | undefined): number | null {
  if (!config || myGroup == null || config.group_count <= 1) return null;
  return myGroup >= 1 && myGroup <= config.group_count ? myGroup : null;
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

/** Where a (Creator, Fan) stands against the picks: served (`in`); a resolved
 *  mismatch (`out`: his group is not the pick, or the pick is above the split's
 *  count, which groupOf never answers) — the evidence he left the queue; or
 *  `held`: the Creator's split is still loading or its read failed, so neither. */
export type InboxVerdict = "in" | "out" | "held";

export interface InboxGate {
  /** One check for live rows and snapshot entries alike. */
  of: (accountId: string, fanId: FanId) => InboxVerdict;
  /** Picked Creators whose split is still loading (not loaded yet). */
  pending: ReadonlySet<string>;
  /** Picked Creators whose split read failed (failed). */
  failed: ReadonlySet<string>;
}

/** The Split Inbox gate: a Creator in `picks` (Creator id → group, the
 *  Creators in play only) serves only the Fans of its picked group, and none
 *  unfiltered (held while its split loads or after a failed read). A Creator
 *  absent from `picks` (All inboxes) serves every Fan. */
export function inboxGate(
  picks: Readonly<Record<string, number>>,
  splits: ReadonlyMap<string, InboxSplit>,
): InboxGate {
  const pending = new Set<string>();
  const failed = new Set<string>();
  const configs = new Map<string, SplitInboxConfig>();
  for (const aid of Object.keys(picks)) {
    const split = splits.get(aid);
    if (!split || split.status === "pending") pending.add(aid);
    else if (split.status === "error") failed.add(aid);
    else configs.set(aid, split.config);
  }
  const of = (aid: string, fanId: FanId): InboxVerdict => {
    if (!Object.hasOwn(picks, aid)) return "in";
    const config = configs.get(aid);
    if (!config) return "held";
    return groupOf(fanId, config) === picks[aid] ? "in" : "out";
  };
  return { of, pending, failed };
}
