"use client";

/**
 * NotificationBell — top-nav bell with a tab-local counter.
 *
 * Badge model (simplified):
 *   • Starts at 0 on every tab load / reload.
 *   • Bumps +1 on every `chatterly:notif-arrived` window event
 *     (dispatched by the toaster on each SSE arrival).
 *   • Resets to 0 when the bell is opened, when the user clicks a row
 *     in the dropdown, or when a toast is clicked elsewhere
 *     (`chatterly:notif-cleared` event).
 *
 * Popouts each maintain their own counter — no localStorage sync, no
 * cross-tab math. The previous baseline + pending-SSE machinery was
 * dropped along with the badge complexity that motivated it.
 *
 * The dropdown's list view still queries OF (when open) and merges with
 * the localStorage history mirror so types OF drops (likes etc.) still
 * show up.
 *
 * The top bar's bell is the header's only one, as Infloww's
 * (`HeaderNotification`: a 36px filled tile with `Bell01Line`). Its panel has
 * "OnlyFans" and "Settings" tabs (NotifSettingsPane). For the owner TopBar
 * passes `agency`, the agency notification centre (`AgencyNotifications`):
 * an "Agency" tab joins them (opened when only it has something new), its kind
 * switches join Settings, and the badge adds its unread count to the arrivals.
 *
 * `variant="messages-pro"` is Messages Pro's "Notifications" Fan List button
 * (docs/spec/phase-01-window-chrome-tabs.md, Notifications): the Clone's
 * green button, the same panel and filters opened inside the Fan List pane,
 * and as its badge the scoped Creator's OnlyFans count (`all` from
 * `/api/of/v2/users/notifications/count`, messages.js:2931-2944) in place of
 * the arrival counter. The badge is hidden at zero, on a failed read and
 * under All Models (not read there), and is read again when the scope
 * changes and when the panel closes. The default `"topbar"` is unchanged.
 * The top bar reaches this module on every route, so the variant's Geometry
 * comes from its Messages-Pro-only caller through `classNames`
 * (docs/spec/phase-06-geometry-pass.md, Interfaces, Shared modules).
 *
 * In that variant a row about a known Fan (one with a Fan id) hands the Fan
 * to `onOpenFan`: the page adds or reuses the Fan's Fan tab and opens its
 * Thread. When the Fan tabs are full the Thread still opens and the panel
 * says "Fan tab limit reached (100)" until the button is next pressed. The
 * top bar's rows and the /notifications page's open the Fan the same way in
 * the Messages Pro window (lib/notificationLink).
 *
 * Also only in that variant, a message notification about a known Fan has a
 * "Reply" field (story 39). Opening it mounts that Fan's message hook and
 * closing it unmounts it. Send posts the text alone through the Composer's
 * send hook (`useSendMessage`) to that Fan's chat as the notification's
 * Creator: on success the field clears and reads "Sent", on failure the text
 * stays, the hook's reason shows and the failed bubble is dropped from the
 * Fan's messages, so the field is the one place the reply is retried.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import { useQueries } from "@tanstack/react-query";
import Link from "next/link";
import { Bell, Settings2 } from "lucide-react";

import { useScope } from "@/contexts/ScopeContext";
import { useActiveAccounts } from "@/hooks/useAccounts";
import { useNotificationSettings } from "@/hooks/useNotificationSettings";
import { useOfNotifCount } from "@/hooks/useOfNotifCount";
import { MoneyRailRestoreButton } from "@/components/MoneyRail";
import { relay } from "@/lib/relay";
import { lazyModule, useLazyModule } from "@/lib/lazyModule";
import { proxyImage } from "@/lib/mediaUrl";
import { cn } from "@/lib/utils";
import { EmptyState } from "@/components/ui/infloww";
import { Bell01Line } from "@/components/shell/inflowwIcons";
import { HEADER_TILE, HEADER_TILE_ICON } from "@/components/shell/headerTile";
import { FAN_TABS_FULL_LABEL, type FanTab } from "@/components/chat/useFanTabs";
import type { FanId } from "@/lib/fanId";
import type { NotificationUser } from "@/lib/moneyRailStorage";
import { notificationHref, onNotificationClick } from "@/lib/notificationLink";
import { usePushState } from "@/lib/webPush";
import { PUSH_HINT, pushHintShown } from "./OsPingSettings";
import { NotifSettingsPane } from "./NotifSettingsPane";
import {
  NOTIF_ARRIVED_EVENT,
  NOTIF_CLEARED_EVENT,
  dispatchNotifCleared,
  mapOfTypeToKey,
  readNotifFilterId,
  readNotifHistory,
  writeNotifFilterId,
  type CachedNotification,
  type NotifTypeKey,
} from "@/lib/notifSettings";
import { Skeleton } from "@/components/ui/Skeleton";
import { type BellPane, initialBellState, notificationBellReducer, ofListOnScreen, OPEN_AGENCY_EVENT } from "./notificationBellReducer";
import { NOTIF_PAGE_SIZE, fmtTime, notifPath, parseList, renderText } from "@/lib/notifText";

/** The bell's tabs, shared with the full Notifications page
 *  (`components/NotificationsPage.tsx`), which reads the same request. */
export type Filter = {
  id: string;
  label: string;
  /** OF `type=` value, or null for "All" (omit param). */
  type: string | null;
};
export const FILTERS: Filter[] = [
  { id: "all",         label: "All",           type: null         },
  { id: "subscribed",  label: "Subscriptions", type: "subscribed" },
  { id: "purchases",   label: "Purchases",     type: "purchases"  },
  { id: "tip",         label: "Tips",          type: "tip"        },
  { id: "commented",   label: "Comments",      type: "commented"  },
  { id: "mentioned",   label: "Mentions",      type: "mentioned"  },
  { id: "favorited",   label: "Likes",         type: "favorited"  },
  { id: "message",     label: "Messages",      type: "message"    },
];

export interface NotificationItem {
  id?: number | string;
  type?: string;
  text?: string;
  description?: string;
  createdAt?: string;
  user?: NotificationUser;
  fromUser?: NotificationUser;
  replacePairs?: Record<string, string>;
  /** Who has answered this message's fan since ("" unknown); see `markNotifHistoryResponded`. */
  respondedBy?: string;
  [k: string]: unknown;
}

/** A feed row tagged with its Creator and its time (0 when undated). */
export interface MergedItem {
  n: NotificationItem;
  accountId: string;
  ts: number;
}

/** The cap on the merged list the bell shows, and the full page's "All". */
export const NOTIF_ALL_CAP = 50;

export { NOTIF_PAGE_SIZE, notifPath, parseList } from "@/lib/notifText";

/** One feed read: its Creator, its offset and how many rows it returned
 *  (undefined until it has data). */
export interface NotificationFeedRead {
  accountId: string;
  offset: number;
  count: number | undefined;
}

/**
 * The bell's feed, shared with the full Notifications page: the Creator scope
 * (the scoped Creator, else every active Creator), one read per Creator and
 * page (`pages[accountId]`, default 1, from offset 0 in steps of
 * `NOTIF_PAGE_SIZE`), and the rows newest first, tagged with their Creator.
 * A row a Creator's earlier page already returned is dropped. Offset 0 keeps
 * the key `["notif-list", accountId, type]` that the Money rail and the
 * toaster's invalidation share; a later page appends its offset.
 */
export function useNotificationFeed(
  type: string | null,
  enabled: boolean,
  pages?: Readonly<Record<string, number>>,
) {
  const { accountId } = useScope();
  const activeAccounts = useActiveAccounts();
  const accountIds = useMemo<string[]>(
    () => (accountId ? [accountId] : activeAccounts.map((a) => a.id)),
    [accountId, activeAccounts],
  );
  const targets = accountIds.flatMap((aid) =>
    Array.from({ length: Math.max(1, pages?.[aid] ?? 1) }, (_, i) => ({ aid, offset: i * NOTIF_PAGE_SIZE })));

  const queries = useQueries({
    queries: targets.map(({ aid, offset }) => ({
      queryKey: (offset === 0 ? ["notif-list", aid, type] : ["notif-list", aid, type, offset]) as readonly unknown[],
      queryFn: async () => parseList(await relay.get(notifPath(type, offset), { accountId: aid })),
      enabled,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    })),
  });

  // Stable signature of the fetched data — the query array itself is a fresh
  // reference every render, so the memo below keys off the per-query update
  // timestamps (which change only when the underlying data does) instead.
  const dataSig = queries.map((q) => q.dataUpdatedAt).join(",");
  const targetSig = `${type}:` + targets.map((t) => `${t.aid}@${t.offset}`).join(",");

  const rows = useMemo<MergedItem[]>(() => {
    const acc: MergedItem[] = [];
    const seen = new Set<string>();
    queries.forEach((q, i) => {
      const aid = targets[i]?.aid;
      if (!aid) return;
      const keys: string[] = [];
      for (const n of q.data ?? []) {
        const key = `${aid}:${n.id}`;
        if (n.id != null && seen.has(key)) continue;
        if (n.id != null) keys.push(key);
        acc.push({ n, accountId: aid, ts: n.createdAt ? Date.parse(n.createdAt) || 0 : 0 });
      }
      for (const key of keys) seen.add(key);
    });
    return acc.sort((a, b) => b.ts - a.ts);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataSig, targetSig]);

  const reads: NotificationFeedRead[] = targets.map((t, i) => ({
    accountId: t.aid,
    offset: t.offset,
    count: queries[i]?.data?.length,
  }));

  return {
    accountIds,
    rows,
    reads,
    loading: enabled && queries.some((q) => q.isLoading),
    error: queries.find((q) => q.error)?.error as Error | undefined,
    /** Re-reads every failed page. */
    refetch: () => { for (const q of queries) if (q.error) void q.refetch(); },
  };
}

/** The bell's dense look, or the full Notifications page's (ticket 19). */
export type NotifSize = "bell" | "page";

const NO_SESSIONS = "No active sessions. Capture one in Manage creators to see notifications.";

/** The feed's place-holder when no Creator has a session. */
export function NoSessionsNote({ size = "bell" }: { size?: NotifSize }) {
  if (size === "page") {
    return (
      <EmptyState
        className="py-16"
        text={NO_SESSIONS}
        action={<Link href="/creators" className="text-[14px] text-accent hover:text-accent-hover">Manage creators</Link>}
      />
    );
  }
  return <div className="p-4 text-xs text-fg-dim">{NO_SESSIONS}</div>;
}

/** The feed's loading, error and empty states; `onRetry` is the page's error Retry. */
export function FeedStatus({ loading, error, empty, size = "bell", onRetry }: {
  loading: boolean;
  error: Error | undefined;
  empty: boolean;
  size?: NotifSize;
  onRetry?: () => void;
}) {
  if (size === "page") {
    if (loading) {
      return (
        <div role="status" aria-label="Loading notifications" className="space-y-px overflow-hidden rounded-[12px]">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-[60px] w-full rounded-none" />)}
        </div>
      );
    }
    if (error) {
      return (
        <EmptyState className="py-16" kind="error" text={error.message || "Failed to load notifications."} onRetry={onRetry} />
      );
    }
    return empty ? <EmptyState className="py-16" text="No notifications" /> : null;
  }
  return (
    <>
      {loading && (
        <div className="p-4 text-xs text-fg-dim">Loading…</div>
      )}
      {error && !loading && (
        <div className="p-4 text-xs text-err">
          {error.message || "Failed to load notifications."}
        </div>
      )}
      {!loading && empty && !error && (
        <div className="p-4 text-xs text-fg-dim">No notifications.</div>
      )}
    </>
  );
}

/** Messages Pro's opener for a notification's Fan: what `useFanTabs().open`
 *  answered, or null when no tab could be written (Employee unresolved). */
export type OpenNotificationFan = (tab: FanTab) => "opened" | "exists" | "full" | null;

/** The Messages Pro variant's Geometry, from its caller: the button, its
 *  icon, its count badge and the panel. Colours and layout stay here. */
export interface NotificationBellClassNames {
  button: string;
  icon: string;
  badge: string;
  panel: string;
}

/** The top bar bell's second feed, the owner's agency notification centre
 *  (`AgencyNotifications`): its unread count, added to the badge, its
 *  panel, the "Agency" tab's body, and its kind switches, shown in the
 *  Settings tab. */
export interface BellAgencyTab {
  unread: number;
  panel: ReactNode;
  settings: ReactNode;
}

/** The top bar's bell, or Messages Pro's "Notifications" button, which
 *  always comes with its Geometry. */
export type NotificationBellProps =
  | {
      variant?: "topbar";
      /** The owner's: the panel gets an "Agency" tab (and its switches in Settings). */
      agency?: BellAgencyTab;
    }
  | {
      variant: "messages-pro";
      /** Opens a row's Fan in a Fan tab. */
      onOpenFan?: OpenNotificationFan;
      /** The variant's Geometry. */
      classNames: NotificationBellClassNames;
    };

/** The panel's tabs: OnlyFans, the owner's Agency (with its unread count), and Settings. */
function paneTabs(agency: BellAgencyTab | undefined): (readonly [BellPane, string, number])[] {
  return [
    ["of", "OnlyFans", 0],
    ...(agency ? [["agency", "Agency", agency.unread] as const] : []),
    ["settings", "Settings", 0],
  ];
}

export function NotificationBell(props: NotificationBellProps = {}) {
  /** The Messages Pro variant's props, or null for the top bar. */
  const proProps = props.variant === "messages-pro" ? props : null;
  const pro = proProps !== null;
  const agency = props.variant === "messages-pro" ? undefined : props.agency;
  // The panel, its tab (OnlyFans, the owner's Agency, or Settings), the arrivals
  // badge and the Fan-tabs-full note: notificationBellReducer.
  const [bell, dispatch] = useReducer(notificationBellReducer, initialBellState);
  // The Agency tab is the owner's; it goes away only when the viewer stops
  // being owner (user not loaded yet, or a chatter): back to OnlyFans before
  // this render draws the panel.
  if (!agency && bell.pane === "agency") dispatch({ type: "pane", pane: "of" });
  const { open, pane, tabsFull } = bell;
  const { accountId } = useScope();
  const activeAccounts = useActiveAccounts();
  // Restore the last-used filter chip. Safe against hydration mismatch:
  // the dropdown (the only place `filter` renders) is closed at SSR time.
  const [filter, setFilter] = useState<Filter>(() => {
    const id = readNotifFilterId();
    return FILTERS.find((f) => f.id === id) ?? FILTERS[0];
  });
  const pickFilter = (f: Filter) => {
    setFilter(f);
    writeNotifFilterId(f.id);
  };
  const push = usePushState();
  const openFan = proProps?.onOpenFan;
  const ref = useRef<HTMLDivElement | null>(null);
  const { settings } = useNotificationSettings();

  // List — fan-out, merged client-side. Enabled only when the panel is
  // open so we don't spam OF on idle pages.
  const feed = useNotificationFeed(filter.type, ofListOnScreen(bell));
  const targetAccountIds = feed.accountIds;

  // The consent banner's "View": open on the Agency tab (only where there is one).
  const hasAgency = !!agency;
  useEffect(() => {
    if (!hasAgency) return;
    const onOpenAgency = () => dispatch({ type: "openAgency" });
    window.addEventListener(OPEN_AGENCY_EVENT, onOpenAgency);
    return () => window.removeEventListener(OPEN_AGENCY_EVENT, onOpenAgency);
  }, [hasAgency]);

  // Badge counter — bump on every arrival (unless the OnlyFans list is on
  // screen), reset on every cleared event.
  useEffect(() => {
    const onArrived = () => dispatch({ type: "arrived" });
    const onCleared = () => dispatch({ type: "cleared" });
    window.addEventListener(NOTIF_ARRIVED_EVENT, onArrived);
    window.addEventListener(NOTIF_CLEARED_EVENT, onCleared);
    return () => {
      window.removeEventListener(NOTIF_ARRIVED_EVENT, onArrived);
      window.removeEventListener(NOTIF_CLEARED_EVENT, onCleared);
    };
  }, []);

  // Messages Pro: the scoped Creator's OnlyFans count. Not read by the top
  // bar, nor under All Models (the count is per Creator).
  const countAccountId = pro ? accountId : null;
  const { count: proCount, refetch: refetchCount } = useOfNotifCount(countAccountId);

  // Opening the bell counts as "seen everything" (the reducer zeroes this
  // bell; the event, any other one).
  const openPanel = () => {
    dispatch({ type: "open", agencyUnread: agency?.unread ?? 0 });
    dispatchNotifCleared();
  };
  // Every close of an open panel: Messages Pro reads its count again.
  const closePanel = useCallback(() => {
    dispatch({ type: "close" });
    if (countAccountId) void refetchCount();
  }, [countAccountId, refetchCount]);
  const togglePanel = () => (open ? closePanel() : openPanel());

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) closePanel();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closePanel(); };
    document.addEventListener("pointerdown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, closePanel]);

  // Re-render when localStorage toast history changes (SSE pushes new
  // entries to it; popouts share via the storage event).
  const [historyTick, bumpHistory] = useState(0);
  useEffect(() => {
    if (!open) return;
    const bump = () => bumpHistory((n) => n + 1);
    const onStorage = (e: StorageEvent) => {
      if (e.key === "chatterly:notif-history:v1") bump();
    };
    window.addEventListener("chatterly:notif-history", bump);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("chatterly:notif-history", bump);
      window.removeEventListener("storage", onStorage);
    };
  }, [open]);

  // The feed's rows plus the localStorage toast history it has not listed.
  const merged = useMemo<MergedItem[]>(() => {
    const acc: MergedItem[] = [...feed.rows];
    const seenIds = new Set<string>();
    for (const m of acc) if (m.n.id != null) seenIds.add(`${m.accountId}:${m.n.id}`);
    const history = readNotifHistory();
    const wantKey: NotifTypeKey | null = filter.id === "all"
      ? null
      : (filter.id as NotifTypeKey);
    for (const aid of targetAccountIds) {
      const items: CachedNotification[] = history[aid] ?? [];
      for (const c of items) {
        if (seenIds.has(`${aid}:${c.id}`)) continue;
        const key = c.typeKey ?? mapOfTypeToKey(c.type);
        if (wantKey && key !== wantKey) continue;
        const ts = c.createdAt ? Date.parse(c.createdAt) || 0 : 0;
        const n: NotificationItem = {
          id: c.id,
          type: c.type,
          text: c.text,
          createdAt: c.createdAt,
          user: c.user,
          replacePairs: c.replacePairs,
          respondedBy: c.respondedBy,
        };
        acc.push({ n, accountId: aid, ts });
      }
    }
    acc.sort((a, b) => b.ts - a.ts);
    return acc.slice(0, NOTIF_ALL_CAP);
    // historyTick re-reads the localStorage history.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feed.rows, targetAccountIds, filter.id, historyTick]);

  const anyLoading = feed.loading;
  const firstError = feed.error;
  const showAccountTag = targetAccountIds.length > 1;
  const accountLabel = useAccountLabelMap(activeAccounts);
  // The top bar badge: unseen arrivals plus the owner's unread agency ones.
  const total = bell.arrivals + (agency?.unread ?? 0);

  return (
    // Messages Pro: an equal share of the Fan List buttons row, whose
    // `relative` the panel opens against.
    <div className={pro ? "flex flex-1" : "relative"} ref={ref}>
      {proProps ? (
        <button
          type="button"
          onClick={togglePanel}
          className={cn(proProps.classNames.button, "relative flex flex-1 items-center justify-center bg-[var(--inf-online,var(--color-ok))] text-white hover:opacity-90")}
        >
          <Bell aria-hidden className={proProps.classNames.icon} />
          {/* The space keeps the badge a word of its own in the button's name. */}
          Notifications{" "}
          {proCount > 0 && (
            <span className={cn(proProps.classNames.badge, "absolute grid place-items-center border-white/70 bg-[var(--inf-online,var(--color-ok))] text-white")}>{proCount}</span>
          )}
        </button>
      ) : (
      // Infloww's `HeaderNotification`: the 36px filled tile, `Bell01Line`,
      // and the count as a pink `HBChip signal="stop"` inside the tile, 8px
      // after the bell (index.9f50f370.js). Our count is the arrivals since
      // the bell was last opened plus the owner's unread agency notifications.
      <button
        type="button"
        // Opens on Agency when only it has something new (the reducer).
        onClick={togglePanel}
        className={cn(HEADER_TILE, "px-2")}
        title="Notifications"
        aria-label="Notifications"
        aria-expanded={open}
      >
        <Bell01Line aria-hidden className={HEADER_TILE_ICON} />
        {total > 0 && (
          <span data-testid="bell-count" className="min-w-5 h-5 px-1.5 grid place-items-center rounded-full bg-pink text-white text-[12px] font-medium leading-none tabular-nums">
            {total > 99 ? "99+" : total}
          </span>
        )}
      </button>
      )}
      {open && (
        <div className={cn(
          proProps
            ? cn(proProps.classNames.panel, "absolute")
            : "fixed inset-x-2 top-[var(--chrome-top)] w-auto max-h-[70vh] sm:absolute sm:inset-x-auto sm:right-0 sm:top-auto sm:mt-1 sm:w-[380px] sm:max-h-[480px]",
          "bg-panel border border-border rounded-lg shadow-xl z-40 flex flex-col",
        )}>
          <div role="tablist" aria-label="Notification feeds" className="flex gap-1 border-b border-border p-2">
            {paneTabs(agency).map(([id, label, n]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={pane === id}
                onClick={() => dispatch({ type: "pane", pane: id })}
                className={cn(
                  "h-7 px-3 inline-flex items-center gap-1.5 rounded-md text-xs font-medium",
                  pane === id ? "bg-nav-surface text-fg" : "text-fg-dim hover:text-fg",
                )}
              >
                {id === "settings" && <Settings2 aria-hidden className="w-3.5 h-3.5" />}
                {label}
                {n > 0 && <span className="min-w-4 h-4 px-1 grid place-items-center rounded-full bg-pink text-white text-[10px] leading-none tabular-nums">{n > 99 ? "99+" : n}</span>}
              </button>
            ))}
          </div>
          {pane === "settings" ? (
            <NotifSettingsPane agency={agency?.settings} />
          ) : pane === "agency" ? (
            // A row that links into the app (e.g. a 2FA row's Browserbase login) closes the panel.
            <div className="flex-1 overflow-y-auto"
              onClick={(e) => { if ((e.target as Element).closest("a[href]")) closePanel(); }}>{agency?.panel}</div>
          ) : targetAccountIds.length === 0 ? (
            <NoSessionsNote />
          ) : (
            <>
              <div className="border-b border-border p-2 flex items-start gap-1">
                <div className="flex flex-wrap gap-1 flex-1 min-w-0">
                  {FILTERS.map((f) => (
                    <button
                      key={f.id}
                      type="button"
                      onClick={() => pickFilter(f)}
                      className={
                        "px-3 py-2 text-xs min-h-[36px] sm:px-2 sm:py-0.5 sm:text-[11px] sm:leading-normal sm:min-h-0 rounded-full border " +
                        (filter.id === f.id
                          ? "bg-accent text-white border-accent"
                          : "border-border text-fg-dim hover:text-fg hover:bg-bg-elev-1")
                      }
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
              </div>
              {/* Money-rail rescue hatch — the bell is mounted everywhere, so
                  it hosts the rail's un-hide control. Renders null when the
                  rail isn't hidden on the current surface. */}
              <MoneyRailRestoreButton />
              {pushHintShown(settings, push) && (
                <button
                  type="button"
                  onClick={() => dispatch({ type: "pane", pane: "settings" })}
                  className="w-full px-3 py-1.5 border-b border-border text-left text-[11px] text-warn hover:bg-bg-elev-1"
                >
                  {PUSH_HINT}
                </button>
              )}
              <div className="flex-1 overflow-y-auto">
                {tabsFull && (
                  <div role="status" className="px-3 py-2 border-b border-border text-xs text-warn">
                    {FAN_TABS_FULL_LABEL}
                  </div>
                )}
                <FeedStatus loading={anyLoading} error={firstError} empty={merged.length === 0} />
                {merged.map((m, i) => (
                  <Row
                    key={`${m.accountId}:${m.n.id ?? i}`}
                    n={m.n}
                    accountId={m.accountId}
                    accountLabel={showAccountTag ? (accountLabel.get(m.accountId) ?? null) : null}
                    reply={pro}
                    onOpenFan={openFan && ((tab) => dispatch({ type: "tabsFull", full: openFan(tab) === "full" }))}
                  />
                ))}
              </div>
            </>
          )}
          {/* The top bar's way to the full page (story 44); Messages Pro's
              signed-off panel is unchanged. */}
          {!pro && pane === "of" && (
            <Link
              href="/notifications"
              onClick={closePanel}
              className="block border-t border-border px-3 py-2 text-center text-xs font-semibold text-accent hover:bg-bg-elev-1/40"
            >
              See all
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

/** One notification row, also the full Notifications page's. */
export function Row({
  n, accountId, accountLabel, reply, onOpenFan, size = "bell",
}: {
  n: NotificationItem;
  accountId: string;
  accountLabel: string | null;
  /** `page`: the full page's 60px row (36px avatar, 14px text, 12px #999 meta). */
  size?: NotifSize;
  /** Messages Pro: a message notification about a known Fan gets "Reply". */
  reply?: boolean;
  /** Set in Messages Pro: a row with a Fan id opens the Fan here. */
  onOpenFan?: (tab: FanTab) => void;
}) {
  const user = n.user || n.fromUser || {};
  const avatar = proxyImage(user.avatar ?? null, accountId);
  const text = renderText(n.text || n.description || "", n.replacePairs, "");
  const href = notificationHref(accountId, user);
  const page = size === "page";
  const body = (
    <>
      <div className={cn(
        "rounded-full overflow-hidden shrink-0 grid place-items-center",
        page ? "w-9 h-9 bg-bg-elev-2" : "w-7 h-7 bg-bg-elev-1",
      )}>
        {avatar ? (
          <img src={avatar} alt="" loading="lazy" decoding="async" className="w-full h-full object-cover" />
        ) : (
          <span className={cn(page ? "text-[14px]" : "text-[10px]", "text-fg-dim")}>
            {(user.name || user.username || "?").slice(0, 1).toUpperCase()}
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className={cn(page ? "text-[14px]" : "text-[12px]", "text-fg leading-snug")}>
          {user.name && (
            <span className={cn("font-medium", page && "text-white [html[data-theme=light]_&]:text-fg")}>{user.name} </span>
          )}
          <span className={page ? undefined : "text-fg-dim"}>{text}</span>
        </div>
        <div className={cn(
          "mt-0.5 flex items-center gap-1.5",
          page ? "text-[12px] text-muted" : "text-[10px] text-fg-dim",
        )}>
          <span>{fmtTime(n.createdAt)}</span>
          {accountLabel && (
            <>
              <span>·</span>
              <span className={page
                ? "rounded-[4px] bg-bg-elev-2 px-1.5 text-[11px] text-fg-dim"
                : "px-1 rounded bg-bg-elev-1 border border-border"}>{accountLabel}</span>
            </>
          )}
        </div>
      </div>
    </>
  );
  const fanId: FanId | undefined = user.id;
  const name = user.name || user.username || `fan ${fanId}`;
  const replyable = reply && fanId != null && mapOfTypeToKey(n.type) === "message";
  // Answered since (Infloww's "has responded"): that line replaces Reply.
  const responded = typeof n.respondedBy === "string" ? n.respondedBy : null;
  const footed = replyable || responded != null;
  // With a Reply field under it, the divider moves to the row and its field.
  const divider = page ? "border-b border-border last:border-b-0" : "border-b border-border/60 last:border-b-0";
  const cls = page
    ? cn("min-h-[60px] px-4 py-3 flex items-start gap-3 hover:bg-bg-elev-2", !footed && divider)
    : cn("px-3 py-2 flex items-start gap-2.5 hover:bg-bg-elev-1/40", !footed && divider);
  const row = onOpenFan && fanId != null ? (
    <button
      type="button"
      className={cn(cls, "w-full text-left")}
      onClick={() => {
        dispatchNotifCleared();
        // The tab's name as the Chat header falls back to it.
        onOpenFan({ accountId, fanId, name });
      }}
    >
      {body}
    </button>
  ) : href ? (
    <a
      href={href}
      className={cls}
      onClick={(e) => {
        dispatchNotifCleared();
        onNotificationClick(e, href);
      }}
    >
      {body}
    </a>
  ) : (
    <div className={cls}>{body}</div>
  );
  if (!footed) return row;
  return (
    <div className={divider}>
      {row}
      {responded != null ? (
        <div className="pr-3 pb-2 pl-12 text-xs text-fg-dim">
          <span className="font-medium text-fg">{responded || "A teammate"}</span> has responded
        </div>
      ) : fanId != null && (
        // Keyed by its Fan: a list keyed by index (an id-less row) can hand this Row another Fan's props, and the
        // line typed for one Fan must never go to another.
        <QuickReply key={`${accountId}:${fanId}:${n.id ?? ""}`} accountId={accountId} fanId={fanId} name={name} />
      )}
    </div>
  );
}

/** The quick-reply field and the Fan's message + send hooks behind it: out of the shell's first load (the bell is in
 *  every page's top bar), fetched once a reply-able row shows. */
const quickReplyField = lazyModule(() => import("./NotificationQuickReply"));

/** A message notification's "Reply" toggle; the field, and with it the Fan's
 *  message hook, is mounted only while open. */
function QuickReply({ accountId, fanId, name }: { accountId: string; fanId: FanId; name: string }) {
  const [open, setOpen] = useState(false);
  // Fetched once a reply-able row is on screen, so a "Reply" tap finds it in.
  const field = useLazyModule(quickReplyField);
  return (
    <div className="pr-3 pb-2 pl-12">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="text-xs font-semibold text-accent hover:underline"
      >
        Reply
      </button>
      {open && field && <field.QuickReplyField accountId={accountId} fanId={fanId} name={name} />}
    </div>
  );
}

export function useAccountLabelMap(accounts: ReturnType<typeof useActiveAccounts>): Map<string, string> {
  return useMemo(() => {
    const m = new Map<string, string>();
    for (const a of accounts) m.set(a.id, a.nickname || a.id);
    return m;
  }, [accounts]);
}
