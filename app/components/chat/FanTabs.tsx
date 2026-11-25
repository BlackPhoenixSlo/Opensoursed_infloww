"use client";


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

const FACT_HEADS = new Set(["chats", "of-user", "fan-spend", "last-purchases"]);

function freshestFirst(qc: QueryClient, queryKey: readonly unknown[]) {
  return qc.getQueryCache().findAll({ queryKey })
    .sort((a, b) => b.state.dataUpdatedAt - a.state.dataUpdatedAt);
}

type TabFacts = { online: boolean; unread: number | null; signal: RowBadge | null };

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
    const badges = rowBadges({
      lastPpvPurchase: activity.lastPpvPurchase.get(key) ?? null,
      lastMessageAt: row?.lastMessage?.createdAt,
      subscriptionStatus: entry?.subscription_status ?? null,
      expiredAt: entry?.expired_at ?? null,
      autoRenewOff: row?.withUser?.autoRenewOff,
    }, now);
    const count = row?.unreadMessagesCount ?? 0;
    out.set(key, {
      online: isFanOnline(row, profile),
      unread: count > 0 ? count : row?.hasUnread ? null : 0,
      signal: badges[0] ?? null,
    });
  }
  return out;
}

function useTabFacts(tabs: FanTab[]): Map<string, TabFacts> {
  const qc = useQueryClient();
  const [tick, setTick] = useState(0);
  useEffect(() => qc.getQueryCache().subscribe((e) => {
    if (e.type === "updated" && FACT_HEADS.has(e.query.queryKey[0] as string)) setTick((n) => n + 1);
  }), [qc]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(() => tabFactsFrom(qc, tabs), [qc, tabs, tick]);
}

const SIGNAL_TONE: Partial<Record<RowBadge, string>> = { New: "text-info", Off: "text-[var(--inf-accent-text,var(--color-accent))]" };

export function FanTabs({ activeKey, onActivate, onClosed }: {
  activeKey: string | null;
  onActivate: (tab: FanTab) => void;
  onClosed: (next: FanTab | null) => void;
}) {
  const { tabs } = useFanTabs();
  const creators = usePlatformAccounts();
  const facts = useTabFacts(tabs);
  const creatorName = (accountId: string) =>
    creators.find((a) => a.id === accountId)?.nickname || accountId;

  const stripRef = useRef<HTMLDivElement | null>(null);
  const tabRefs = useRef(new Map<string, HTMLButtonElement>());

  const focusAfterClose = useCallback((next: FanTab | null) => {
    if (next) tabRefs.current.get(fanTabKey(next.accountId, next.fanId))?.focus();
    else stripRef.current?.focus();
  }, []);
  const closeTab = useFanTabsCloseRule({ activeKey, onClosed, onClosedHere: focusAfterClose });

  return (
    <div ref={stripRef} role="tablist" aria-label="Fan tabs strip" tabIndex={-1} className={cn(G.strip, "flex flex-1 min-w-0 items-end overflow-x-auto")}>
      {tabs.map((t) => {
        const key = fanTabKey(t.accountId, t.fanId);
        const active = key === activeKey;
        const f = facts.get(key);
        const online = f?.online ?? false;
        const presence = online ? "Online" : "Offline";
        const signal = f?.signal ?? null;
        return (
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
                title={`${t.name} · ${creatorName(t.accountId)}`}
                className={cn(O.tabPick, "flex min-w-0 items-center")}
              >
                <span className="min-w-0 truncate">{t.name}</span>
                {f && f.unread !== 0 && <UnreadMiniBadge count={f.unread} />}
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
              <button
                type="button"
                onClick={() => closeTab(key)}
                // Sibling of the tab, not nested: a button cannot nest in a button.
                aria-label={`Close ${t.name}`}
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
      disabled={employeeKey === null || full}
      title={full
        ? FAN_TABS_FULL_LABEL
        : "Pin this chat as a tab so you can switch between conversations without losing it"}
      className={cn(MP.chatHeader.openNew, "hidden md:flex items-center whitespace-nowrap text-[var(--inf-accent-text,var(--color-accent))] hover:bg-bg-elev-1 disabled:opacity-50 disabled:cursor-not-allowed")}
    >
      <ExternalLink aria-hidden className={MP.chatHeader.openNewIcon} />
      <span className={MP.chatHeader.labelText}>Open in new tab</span>
    </button>
  );
}
