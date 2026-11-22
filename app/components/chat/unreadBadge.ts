/**
 * The Unread badge's number (docs/spec/watched-creator-refresher/phase-02-unread-total-first-paint.md, Client badge
 * rules): pure selectors over the tab's Freshness store (lib/creatorFreshness), no store of their own. FanList only
 * reads them.
 *
 * 1. Under a search the badge is today's rule (`chipCountsWithUnreadView` over the searched All set).
 * 2. Else per Creator the Fan List shows, a held Unread total (`values.unread_total`, the Relay's whole-inbox count)
 *    wins over All-list flags and #881's Unread view; a Creator without one counts by today's rule over its rows
 *    only. The badge is the sum. With no Creator holding one (the Knob off) it is today's number, the same call.
 * 3. First paint: the accounts copy says off → today's number at once; on or unknown → no number until the
 *    network accounts answer is in the store (or failed). No timer.
 *
 * `unreadBadgeSources` is Phase 3's input (the chip's "as of", components/chat/dataAge `badgeAge`): each counted
 * Creator's confirmation time.
 */

import type { CreatorFreshnessState, Freshness } from "@/lib/creatorFreshness";
import type { UnreadView } from "@/lib/chatsCache";
import type { OFChatItem } from "@/lib/relay";
import { chipCountsWithUnreadView, type FanSortDeps } from "./fanListSort";

/** Whether the Relay sends Unread totals, read off an accounts answer's rows: a row's `freshness.values` holds the
 *  `unread_total` key (a null value included) → true; rows but no key → false; no rows → null (unknown). */
export function totalsOn(rows: ReadonlyArray<{ freshness?: Freshness | null }> | null | undefined): boolean | null {
  if (!rows?.length) return null;
  return rows.some((r) => !!r.freshness?.values && "unread_total" in r.freshness.values);
}

/** The accounts query as the badge sees it: only the persisted copy so far, a network answer of this page, or failed. */
export type AccountsAnswer = "none" | "network" | "error";

/** Rule 3: the badge may show a number. `on` is `totalsOn` over the accounts rows held now; `seeded`: the Freshness
 *  store holds anything (the network answer's seed lands one effect after the answer). */
export function badgeReady(on: boolean | null, answer: AccountsAnswer, seeded: boolean): boolean {
  if (answer === "error") return true;
  if (answer === "none") return on === false;
  return on !== true || seeded;
}

const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** The Creator's held Unread total, or null (none held, the Knob off, none confirmed yet, malformed). */
export function heldTotal(state: CreatorFreshnessState, accountId: string): { n: number; at: number } | null {
  const t = state[accountId]?.values.unread_total;
  return t && isNum(t.n) && isNum(t.at) ? t : null;
}

/** One counted Creator's confirmation time: `at` = the later of its Last refresh and its total's own `at` (epoch ms,
 *  Relay clock; null: neither). Never `creator_warmed`'s (a reused warm republishes it with no read). That is the
 *  total's own confirmation time: every Last refresh is a landed `/users/me`, which confirms the total or, carrying no
 *  counter, drops it (service unread_total.observe), and an unchanged total publishes no new `at`. */
export interface BadgeSource { account_id: string; at: number | null }

/** The confirmation time of each of `accountIds` (Phase 2's `fromTotal`), in that order. */
export function unreadBadgeSources(state: CreatorFreshnessState, accountIds: readonly string[]): BadgeSource[] {
  return accountIds.map((account_id) => {
    const last = state[account_id]?.at;
    const t = heldTotal(state, account_id)?.at;
    const ats = [last, t].filter(isNum);
    return { account_id, at: ats.length ? Math.max(...ats) : null };
  });
}

/** Today's rule over the rows of `creators` (null: every row, today's number). */
export type Fallback = (creators: ReadonlySet<string> | null) => number;

export interface UnreadBadge {
  /** null: no number yet (rule 3). */
  n: number | null;
  /** The shown Creators counted from their held total. */
  fromTotal: string[];
  /** The shown Creators counted by today's rule. */
  fallback: string[];
}

/** The badge (rules 1–3) over the Creators the Fan List shows. */
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

/** Today's Unread number (`chipCountsWithUnreadView`) over the All set, narrowed to `creators`' rows and their part of
 *  #881's view; null: every row, unchanged. */
export function todaysUnread(
  allRows: OFChatItem[], view: UnreadView | null, deps: Pick<FanSortDeps, "isOwed">,
  creators: ReadonlySet<string> | null, accountOf: (c: OFChatItem) => string,
): number {
  if (!creators) return chipCountsWithUnreadView(allRows, view, deps).unreadCount;
  const mine = (c: OFChatItem) => creators.has(accountOf(c));
  return chipCountsWithUnreadView(allRows.filter(mine), view && { ...view, rows: view.rows.filter(mine) }, deps)
    .unreadCount;
}
