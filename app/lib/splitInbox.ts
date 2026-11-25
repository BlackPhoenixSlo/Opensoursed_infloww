import { queryOptions } from "@tanstack/react-query";

import type { FanId } from "@/lib/fanId";
import { relay, type RelayContext } from "@/lib/relay";

export interface SplitInboxConfig {
  group_count: number;
  assignments: Record<string, number>;
  chatter_groups?: Record<string, number>;
}

export interface SplitInboxResponse {
  account_id: string;
  config: SplitInboxConfig;
  my_group?: number | null;
}

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

export function lockedGroup(config: SplitInboxConfig | null, myGroup: number | null | undefined): number | null {
  if (!config || myGroup == null || config.group_count <= 1) return null;
  return myGroup >= 1 && myGroup <= config.group_count ? myGroup : null;
}

const BG_CTX: RelayContext = { priority: "background" };

export const splitInboxKey = (accountId: string | null) => ["split-inbox", accountId] as const;

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

export type InboxSplit =
  | { status: "pending" }
  | { status: "error" }
  | { status: "success"; config: SplitInboxConfig };

export type InboxVerdict = "in" | "out" | "held";

export interface InboxGate {
  of: (accountId: string, fanId: FanId) => InboxVerdict;
  pending: ReadonlySet<string>;
  failed: ReadonlySet<string>;
}

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

export interface ScopeSplit {
  config: SplitInboxConfig | null;
  myGroup: number | null;
  failed?: boolean;
}

export interface InboxScope {
  groupCount: number;
  locked: number | null;
  of: ((accountId: string, fanId: FanId) => boolean) | null;
  allLoaded: boolean;
  pending: ReadonlySet<string>;
  failed: ReadonlySet<string>;
}

export function inboxScope(splits: ReadonlyMap<string, ScopeSplit>, picked: number | null): InboxScope {
  const all = [...splits.values()];
  const loaded = all.flatMap((s) => (s.config ? [s.config] : []));
  const groupCount = Math.max(1, ...loaded.map((c) => c.group_count));
  const locks = all.map((s) => lockedGroup(s.config, s.myGroup));
  const locked = locks.length > 0 && locks.every((g) => g != null && g === locks[0]) ? locks[0] : null;
  const selected = locked ?? picked;
  const picks: Record<string, number> = {};
  const reads = new Map<string, InboxSplit>();
  const conflicts = new Set<string>();
  for (const [aid, split] of splits) {
    const lock = lockedGroup(split.config, split.myGroup);
    if (selected != null && lock != null && lock !== selected) conflicts.add(aid);
    const group = selected ?? lock;
    if (group != null) picks[aid] = group;
    reads.set(aid, split.config
      ? { status: "success", config: split.config }
      : { status: split.failed ? "error" : "pending" });
  }
  const gate = inboxGate(picks, reads);
  const of = Object.keys(picks).length === 0 ? null : (aid: string, fanId: FanId) =>
    !conflicts.has(aid) && (picked == null || reads.has(aid)) && gate.of(aid, fanId) === "in";
  return { groupCount, locked, of, allLoaded: loaded.length === all.length, pending: gate.pending, failed: gate.failed };
}
