"use client";

/**
 * FanTabs — the Fan tabs strip in the Fan tabs row (the Clone's
 * `.thread-tabs`, docs/spec/phase-01-window-chrome-tabs.md), and "Open in new
 * tab", which the Chat header renders to add one. Both read the window's Fan
 * tabs store (`useFanTabs`).
 *
 * - A Fan tab shows, in order, the online dot, the Fan's name (cut short
 *   inside its 190px cap), the unread count, the signal and ✕. Its tooltip
 *   is "<Fan> · <Creator>" (messages.js:2560).
 * - The dot, count and signal are the facts the Fan List row reads, taken
 *   from the query cache under the row's keys with no fetch of their own
 *   (`tabFactsFrom`): a tab whose Fan has nothing cached shows its stored
 *   name and the offline dot only.
 * - The tab whose key is `activeKey` (the conversation open in the Thread)
 *   shows the 2px inset top line and is `aria-selected`.
 * - Clicking a tab hands it, as stored, to `onActivate`, which opens its
 *   Thread. Right-clicking it offers "Open in a new window" (the Fan List
 *   row's menu, `OpenInNewWindowMenu`): a Pop-out window at the Fan's Deep
 *   link.
 * - ✕ closes a tab (messages.js:2573-2580). Closing the active tab hands the
 *   last remaining tab to `onClosed`, which opens it; closing the last tab,
 *   active or not, hands it null, which leaves the Thread empty. Closing an
 *   inactive tab while others remain calls nothing. Focus moves to the
 *   active tab, or to the last remaining tab when the open Fan has none, or
 *   to the strip when none remain.
 * - A tab closed in another window (a `storage` event) runs the same rule,
 *   so the windows never disagree, but focus stays where it is. Switching
 *   Employee swaps the whole tab set and closes nothing. The rule is
 *   `useFanTabsCloseRule`'s; below lg, where the strip is not mounted, the
 *   page runs it instead.
 * - A tab hidden because its Creator has left the relay (`useFanTabs`) is not
 *   closed: only a tab gone from storage runs the close rule above.
 * - "Open in new tab" adds a tab for the conversation open in the Thread at
 *   the end of the strip, once (messages.js:2588-2596). At `FAN_TABS_MAX`
 *   stored tabs it is disabled with "Fan tab limit reached (100)" until a
 *   tab closes.
 */

import { ExternalLink } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";

import { usePlatformAccounts } from "@/hooks/useAccounts";
import type { SpendBatchResp } from "@/hooks/useFanSpend";
import { fanActivityFrom, type TransactionRow } from "@/hooks/useLastPurchases";
import { ofUserNameKey } from "@/hooks/useOFUser";
import type { FanId } from "@/lib/fanId";
import { MP } from "@/lib/messagesPro";
import { fanDeepLinkHref } from "@/lib/nav";
import type { OFChatItem } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { OpenInNewWindowMenu } from "./OpenInNewWindowMenu";
import { UnreadMiniBadge } from "./UnreadMiniBadge";
import { ROW_BADGE_LABEL, type RowBadge, rowBadges } from "./fanRowBadges";
import { isFanOnline, type Seen } from "./isFanOnline";
import { FAN_TABS_FULL_LABEL, fanTabKey, useFanTabs, useFanTabsCloseRule, type FanTab } from "./useFanTabs";

const G = MP.fanTabs;
const O = MP.ours.FanTabs;

/** The query-key heads of the Fan List row's facts: its chat rows
 *  (`useChatList`), the Fan's profile (`["of-user", aid, fid]`), the
 *  spend-batch status (`useFanSpend`) and Fan activity (`useFanActivity`). */
const FACT_HEADS = new Set(["chats", "of-user", "fan-spend", "last-purchases"]);

/** The newest data first, so a fact cached by several views (the Fan List's
 *  filters, two spend chunks) reads as the freshest one. */
function freshestFirst(qc: QueryClient, queryKey: readonly unknown[]) {
  return qc.getQueryCache().findAll({ queryKey })
    .sort((a, b) => b.state.dataUpdatedAt - a.state.dataUpdatedAt);
}

type TabFacts = { online: boolean; unread: number | null; signal: RowBadge | null };

/** Every tab's facts by `fanTabKey`, read from the cache alone as of now: one
 *  freshest-first pass over the chat rows and the spend batches, and one
 *  activity pass over the tabbed Creators' feeds. */
function tabFactsFrom(qc: QueryClient, tabs: FanTab[]): Map<string, TabFacts> {
  const now = Date.now();
  const keys = new Set(tabs.map((t) => fanTabKey(t.accountId, t.fanId)));
  const rows = new Map<string, OFChatItem>();
  for (const q of freshestFirst(qc, ["chats"])) {
    for (const p of (q.state.data as { pages?: { rows?: OFChatItem[] }[] } | undefined)?.pages ?? []) {
      for (const c of p.rows ?? []) {
        const key = fanTabKey(c.__accountId ?? "", c.withUser.id);
        if (keys.has(key) && !rows.has(key)) rows.set(key, c);
      }
    }
  }
  const spend = new Map<string, SpendBatchResp["spend"][string]>();
  for (const q of freshestFirst(qc, ["fan-spend"])) {
    const aid = String(q.queryKey[1]);
    for (const [fid, entry] of Object.entries((q.state.data as SpendBatchResp | undefined)?.spend ?? {})) {
      const key = fanTabKey(aid, fid);
      if (keys.has(key) && !spend.has(key)) spend.set(key, entry);
    }
  }
  const aids = Array.from(new Set(tabs.map((t) => t.accountId)));
  const activity = fanActivityFrom(aids.map((aid) => [aid, qc.getQueryData<TransactionRow[]>(["last-purchases", aid])] as const));

  const out = new Map<string, TabFacts>();
  for (const t of tabs) {
    const key = fanTabKey(t.accountId, t.fanId);
    const row = rows.get(key);
    const entry = spend.get(key);
    const profile = qc.getQueryData<Seen>(ofUserNameKey(t.accountId, t.fanId));
    // Phase 2's Row badge rules, in their order (New, 🔥, ❄️, ❌, Off): the
    // signal is the first one lit.
    const badges = rowBadges({
      lastPpvPurchase: activity.lastPpvPurchase.get(key) ?? null,
      lastMessageAt: row?.lastMessage?.createdAt,
      subscriptionStatus: entry?.subscription_status ?? null,
      expiredAt: entry?.expired_at ?? null,
      autoRenewOff: row?.withUser?.autoRenewOff,
    }, now);
    // The row's unread rule (`FanRow.tsx:82`): unread when OF says so or a
    // count is set; the count when there is one, else null (no number).
    const count = row?.unreadMessagesCount ?? 0;
    out.set(key, {
      online: isFanOnline(row, profile),
      unread: count > 0 ? count : row?.hasUnread ? null : 0,
      signal: badges[0] ?? null,
    });
  }
  return out;
}

/** The tabs' facts, rebuilt when the tabs change or any of the row's facts
 *  update in the cache (the `app/group/page.tsx:352-363` subscription). */
function useTabFacts(tabs: FanTab[]): Map<string, TabFacts> {
  const qc = useQueryClient();
  const [tick, setTick] = useState(0);
  useEffect(() => qc.getQueryCache().subscribe((e) => {
    if (e.type === "updated" && FACT_HEADS.has(e.query.queryKey[0] as string)) setTick((n) => n + 1);
  }), [qc]);
  // `tick` is the re-read trigger: the cache itself is not a dependency.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => tabFactsFrom(qc, tabs), [qc, tabs, tick]);
}

/** The signal's colour where it is a word, as on the row (New on `info`,
 *  Off in `accent`); the glyphs carry their own. */
const SIGNAL_TONE: Partial<Record<RowBadge, string>> = { New: "text-info", Off: "text-[var(--inf-accent-text,var(--color-accent))]" };

export function FanTabs({ activeKey, onActivate, onClosed }: {
  activeKey: string | null;
  onActivate: (tab: FanTab) => void;
  /** After ✕: the tab to open next, or null for an empty Thread. */
  onClosed: (next: FanTab | null) => void;
}) {
  const { tabs } = useFanTabs();
  const creators = usePlatformAccounts();
  const facts = useTabFacts(tabs);
  // The house fallback (`AccountChips.tsx`, `NotificationBell.tsx`): a Creator
  // not (yet) among the loaded ones is named by its id.
  const creatorName = (accountId: string) =>
    creators.find((a) => a.id === accountId)?.nickname || accountId;

  const stripRef = useRef<HTMLDivElement | null>(null);
  const tabRefs = useRef(new Map<string, HTMLButtonElement>());

  // The close rule (`useFanTabsCloseRule`), with focus after a ✕ here: the
  // tab active once the close is done, or the strip when none remain, as the
  // Creator tabs' pattern does.
  const focusAfterClose = useCallback((next: FanTab | null) => {
    if (next) tabRefs.current.get(fanTabKey(next.accountId, next.fanId))?.focus();
    else stripRef.current?.focus();
  }, []);
  const closeTab = useFanTabsCloseRule({ activeKey, onClosed, onClosedHere: focusAfterClose });

  return (
    // Focusable from script only: focus lands here when the last tab closes.
    <div ref={stripRef} role="tablist" aria-label="Fan tabs strip" tabIndex={-1} className={cn(G.strip, "flex flex-1 min-w-0 items-end overflow-x-auto")}>
      {tabs.map((t) => {
        const key = fanTabKey(t.accountId, t.fanId);
        const active = key === activeKey;
        const f = facts.get(key);
        const online = f?.online ?? false;
        const presence = online ? "Online" : "Offline";
        const signal = f?.signal ?? null;
        return (
          // The Fan window URL (spec, Contracts): the Deep link in a Pop-out window.
          <OpenInNewWindowMenu key={key} href={fanDeepLinkHref(t.accountId, t.fanId)}>
            <div
              className={cn(
                G.tab,
                "inline-flex flex-none items-center whitespace-nowrap",
                active
                  ? cn("bg-accent/15 border-accent/55 text-fg inset-shadow-accent", G.tabActive)
                  : "bg-[var(--inf-fan-tab,var(--color-panel))] border-border text-fg-dim hover:bg-bg-elev-1 hover:text-fg",
              )}
            >
              {/* The dot is the tab's sibling of the pick target, as ✕ is, so
               *  presence stays out of the tab's accessible name. */}
              <span
                role="img"
                aria-label={presence}
                title={presence}
                className={cn(G.dot, "flex-none", online ? "bg-ok" : "bg-[var(--inf-offline,var(--color-fg-dim))]")}
              />
              <button
                ref={(el) => {
                  if (el) tabRefs.current.set(key, el);
                  else tabRefs.current.delete(key);
                }}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => onActivate(t)}
                // The Clone's tooltip (messages.js:2560): the whole name, which
                // the tab may cut short, and its Creator.
                title={`${t.name} · ${creatorName(t.accountId)}`}
                className={cn(O.tabPick, "flex min-w-0 items-center")}
              >
                <span className="min-w-0 truncate">{t.name}</span>
                {f && f.unread !== 0 && <UnreadMiniBadge count={f.unread} />}
                {/* A space for the accessible name ("Name 3 unread …"); a flex
                 *  row drops whitespace-only text, so it does not show. */}
                {signal && " "}
                {signal && (
                  <span
                    role="img"
                    aria-label={ROW_BADGE_LABEL[signal]}
                    title={ROW_BADGE_LABEL[signal]}
                    className={cn("flex-none", SIGNAL_TONE[signal])}
                  >
                    {signal}
                  </span>
                )}
              </button>
              {/* The ✕ is the tab's sibling inside the tablist, not inside the
               *  tab: a button cannot nest in a button, and inside the tab it
               *  would join the tab's accessible name (as the Creator tab's). */}
              <button
                type="button"
                onClick={() => closeTab(key)}
                aria-label={`Close ${t.name}`}
                // The Clone's tooltip (messages.js:2562).
                title="Close tab"
                className={cn(G.close, "flex-none opacity-50 hover:opacity-100 hover:bg-white/15")}
              >
                <span aria-hidden>✕</span>
              </button>
            </div>
          </OpenInNewWindowMenu>
        );
      })}
    </div>
  );
}

/** "Open in new tab" in the Chat header, for the conversation open in the
 *  Thread, with the Clone's `.open-new` Geometry (`MP.chatHeader.openNew`).
 *  It shows from md up (spec H9, F14); the Fan tabs row shows from lg up, so
 *  between md and lg a tab it adds is stored and shows once the row does. */
export function OpenInNewTabButton({ accountId, fanId, name }: {
  accountId: string;
  fanId: FanId;
  name: string;
}) {
  const { open, full, employeeKey } = useFanTabs();
  return (
    <button
      type="button"
      onClick={() => open({ accountId, fanId, name })}
      // Nothing is written until the Employee resolves, and nothing is
      // evicted at the cap.
      disabled={employeeKey === null || full}
      // The Clone's `#tbOpen` tooltip (mh:707), or why the button is off.
      title={full
        ? FAN_TABS_FULL_LABEL
        : "Pin this chat as a tab so you can switch between conversations without losing it"}
      className={cn(MP.chatHeader.openNew, "hidden md:flex items-center whitespace-nowrap text-[var(--inf-accent-text,var(--color-accent))] hover:bg-bg-elev-1 disabled:opacity-50 disabled:cursor-not-allowed")}
    >
      <ExternalLink aria-hidden className={MP.chatHeader.openNewIcon} />
      {/* Screen-reader text in a Thread narrower than 448px (Compare CH3). */}
      <span className={MP.chatHeader.labelText}>Open in new tab</span>
    </button>
  );
}
