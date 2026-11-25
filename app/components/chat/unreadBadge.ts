import type { CreatorFreshnessState, Freshness } from "@/lib/creatorFreshness";
import type { UnreadView } from "@/lib/chatsCache";
import type { OFChatItem } from "@/lib/relay";
import { chipCountsWithUnreadView, type FanSortDeps } from "./fanListSort";

export function totalsOn(rows: ReadonlyArray<{ freshness?: Freshness | null }> | null | undefined): boolean | null {
  if (!rows?.length) return null;
  return rows.some((r) => !!r.freshness?.values && "unread_total" in r.freshness.values);
}

export type AccountsAnswer = "none" | "network" | "error";

export function badgeReady(on: boolean | null, answer: AccountsAnswer, seeded: boolean): boolean {
  if (answer === "error") return true;
  if (answer === "none") return on === false;
  return on !== true || seeded;
}

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

export function heldTotal(state: CreatorFreshnessState, accountId: string): { n: number; at: number } | null {
  const t = state[accountId]?.values.unread_total;
  return t && isNum(t.n) && isNum(t.at) ? { n: t.n, at: t.at } : null;
}

export interface BadgeSource { account_id: string; at: number | null }

export function unreadBadgeSources(state: CreatorFreshnessState, accountIds: readonly string[]): BadgeSource[] {
  return accountIds.map((account_id) => {
    const last = state[account_id]?.at;
    const t = heldTotal(state, account_id)?.at;
    // Never creator_warmed: a reused warm republishes it with no read.
    const ats = [last, t].filter(isNum);
    return { account_id, at: ats.length ? Math.max(...ats) : null };
  });
}

export type Fallback = (creators: ReadonlySet<string> | null) => number;

export interface UnreadBadge {
  n: number | null;
  fromTotal: string[];
  fallback: string[];
}

export function badgeUnread(
  state: CreatorFreshnessState, shownCreators: readonly string[], fallbackCount: Fallback,
  gate: { ready: boolean; search: boolean },
): UnreadBadge {
  if (!gate.ready) return { n: null, fromTotal: [], fallback: [] };
  if (gate.search) return { n: fallbackCount(null), fromTotal: [], fallback: [...shownCreators] };
  const fromTotal: string[] = [];
  const fallback: string[] = [];
  let sum = 0;
  for (const aid of shownCreators) {
    const t = heldTotal(state, aid);
    if (t) { fromTotal.push(aid); sum += t.n; } else fallback.push(aid);
  }
  if (fromTotal.length === 0) return { n: fallbackCount(null), fromTotal, fallback };
  return { n: sum + (fallback.length ? fallbackCount(new Set(fallback)) : 0), fromTotal, fallback };
}

export function todaysUnread(
  allRows: OFChatItem[], view: UnreadView | null, deps: Pick<FanSortDeps, "isOwed">,
  creators: ReadonlySet<string> | null, accountOf: (c: OFChatItem) => string,
): number {
  if (!creators) return chipCountsWithUnreadView(allRows, view, deps).unreadCount;
  const mine = (c: OFChatItem) => creators.has(accountOf(c));
  return chipCountsWithUnreadView(allRows.filter(mine), view && { ...view, rows: view.rows.filter(mine) }, deps)
    .unreadCount;
}
