"use client";

/**
 * MessagesPro — the one Messages Pro tree (ADR-0002). The index page, the
 * Pop-out window and the Deep link (`deepLink`) all render it.
 *
 * Layout (lg+): a column of the Window header, the Fan tabs row, then the
 * panes taking the height left: conversation list (FanList, scope-aware) |
 * thread (ChatSurface) | fan insights (FanDrawer,
 * open on selection and closable from the Thread's "Fan insights" toggle).
 * Below lg neither top row renders and it collapses to one pane at a time.
 *
 * Why selection lives here: switching chats should unmount and remount
 * the ChatSurface (fresh hooks, fresh refs), which we do via `key=`.
 * That's the React-idiomatic answer to the desktop-app's `connectionId`
 * key pattern from §12.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useIsRestoring, useQuery, useQueryClient } from "@tanstack/react-query";

import { FanList, type FanListSelection } from "@/components/chat/FanList";
import { FanListButtons } from "@/components/chat/FanListButtons";
import { ChatSurface } from "@/components/chat/ChatSurface";
import { FanTabsRow } from "@/components/chat/FanTabsRow";
import { InflowwPalette } from "@/components/chat/InflowwPalette";
import { FAN_TABS_FULL_LABEL, fanTabKey, useFanTabs, useFanTabsCloseRule, type FanTab } from "@/components/chat/useFanTabs";
import { ThreadEmptyState } from "@/components/chat/ThreadEmptyState";
import { WindowHeader } from "@/components/chat/WindowHeader";
import { useCreatorTabs } from "@/components/chat/useCreatorTabs";
import { ScopeSelect } from "@/components/shell/ScopeSelect";
import { useInboxRealtime } from "@/hooks/useInboxRealtime";
import { ofUserFullKey, ofUserNameKey, ofUserNameQuery, ofUserQuery, type OFUserName } from "@/hooks/useOFUser";
import { useOnlineSubscribers } from "@/hooks/useOnlineSubscribers";
import { fetchAllVaultLists } from "@/hooks/useVaultMedia";
import { usePlatformAccounts } from "@/hooks/useAccounts";
import { usePickAllModels } from "@/hooks/usePickAllModels";
import { useSfw } from "@/hooks/useBlurMode";
import { useHotkeys } from "@/hooks/useHotkeys";
import { useIsDesktop } from "@/hooks/useIsDesktop";
import { useScope } from "@/contexts/ScopeContext";
import { MP } from "@/lib/messagesPro";
import { FAN_TAB_PARAM, setFanTabOpener } from "@/lib/notificationLink";
import { cn } from "@/lib/utils";
import { relay, type OFChatItem, type OFUserMini } from "@/lib/relay";
import { sameUserId, type FanId } from "@/lib/fanId";

/** How long "Fan tab limit reached (100)" shows after a notification outside the panel. */
const TABS_FULL_NOTICE_MS = 8_000;

/** The Creator and Fan a Deep link (`/messages-pro/<accountId>/<fanId>`) names. */
export interface MessagesProDeepLink {
  accountId: string;
  fanId: FanId;
}

export function MessagesPro({ deepLink }: { deepLink?: MessagesProDeepLink } = {}) {
  // A Deep link arrives with its Fan selected, before the Fan List has loaded.
  // `arrival` holds the link while that first selection stands: its Thread is built
  // from the profile lookup below and starts with Fan insights closed. Any
  // selection made after it is in-app (insights open).
  const [selected, setSelected] = useState<FanListSelection | null>(
    () => deepLink ? { ...deepLink, chat: deepLinkChat(deepLink, undefined) } : null,
  );
  const [arrival, setArrival] = useState(deepLink);
  // "Online Fans": the Fan List shows only online Fans while on.
  const [onlineOnly, setOnlineOnly] = useState(false);
  const desktop = useIsDesktop();
  useInboxRealtime();
  const qc = useQueryClient();
  const accounts = usePlatformAccounts();
  const { pickAll } = usePickAllModels();
  const { scope, setScope } = useScope();

  // While Online Fans is on, the scoped Creator's OnlyFans online list (one
  // page, latest activity first): those Fans count as online alongside the
  // row rule. Under All Models it is not read (one read per Creator is the
  // fan-out the warm-ups below avoid). A failed read leaves the row rule.
  const onlineAccountId = onlineOnly && scope.kind === "model" ? scope.accountId : null;
  const onlineListQ = useOnlineSubscribers(onlineAccountId);
  const onlineIds = onlineListQ.data?.ids;
  const onlineListFailed = onlineListQ.isError;

  // The Deep link Fan's profile, so its Thread header shows a name and avatar
  // without waiting for the Fan List. The same lookup the one-Fan page used;
  // it lands in the per-Fan profile cache the Thread and the Fan List read.
  const profileQ = useQuery({
    ...ofUserNameQuery(deepLink?.accountId ?? "", deepLink?.fanId ?? ""),
    enabled: !!deepLink,
    refetchOnWindowFocus: false,
  });
  // Stable per link: the Deep link page memoizes `deepLink`.
  const arrivalChat = useMemo(
    () => arrival && deepLinkChat(arrival, profileQ.data),
    [arrival, profileQ.data],
  );

  // Selecting a Fan by hand. On a Deep link, `msg` names a message in the
  // linked Fan's Thread only: drop it from the URL HERE, before the next
  // Thread mounts, because that Thread reads `msg` in its own effect, which
  // runs before any effect of ours, and would page back through up to six
  // live OnlyFans calls looking for it.
  const handleSelect = useCallback((sel: FanListSelection) => {
    if (deepLink && !(sel.accountId === deepLink.accountId && sameUserId(sel.fanId, deepLink.fanId))) {
      stripSearchParam("msg");
    }
    setArrival(undefined);
    setSelected(sel);
  }, [deepLink]);

  // Clicking a Fan tab opens its Thread the way a Deep link does, from the
  // Creator and the Fan id (with whatever profile the cache holds). A tab of
  // another Creator first scopes that Creator, in the same update as the
  // selection, so the scope guard below never sees the old scope with the new
  // Fan. Under All Models the scope stays. The URL does not change. The active
  // tab's Fan is already open, with its full chat row (unread flag, read
  // marker, name): clicking it again changes nothing, rather than swapping
  // that row for the thin Deep link chat.
  const handleActivateTab = useCallback((tab: FanTab) => {
    if (selected && selected.accountId === tab.accountId && sameUserId(selected.fanId, tab.fanId)) return;
    if (scope.kind === "model" && scope.accountId !== tab.accountId) {
      setScope({ kind: "model", accountId: tab.accountId });
    }
    const link = { accountId: tab.accountId, fanId: tab.fanId };
    handleSelect({
      ...link,
      chat: deepLinkChat(link, qc.getQueryData<OFUserName | null>(ofUserNameKey(tab.accountId, tab.fanId))),
    });
  }, [selected, scope, setScope, handleSelect, qc]);

  // A notification row about a Fan: add the Fan's tab, or reuse the one it
  // has, and open it as a Fan tab click does. At the cap nothing is added and
  // the Thread still opens; the panel tells the Employee why. Nothing is
  // written while the Employee is unresolved (`useFanTabs`).
  const { open: openFanTab, close: closeFanTab, employeeKey: fanTabsEmployeeKey } = useFanTabs();
  const handleOpenNotificationFan = useCallback((tab: FanTab) => {
    const result = fanTabsEmployeeKey === null ? null : openFanTab(tab);
    handleActivateTab(tab);
    return result;
  }, [fanTabsEmployeeKey, openFanTab, handleActivateTab]);
  // A money notification's `?refresh=media` (the Fan just paid): read again
  // what the header's manual ↻ reads (ChatSurface.handleRefresh), plus the
  // full profile (the money block), which never refetches on mount (useOFUser).
  const refreshMoney = useCallback(({ accountId, fanId }: { accountId: string; fanId: FanId }) => {
    void qc.invalidateQueries({ queryKey: ["messages", accountId, fanId] });
    void qc.invalidateQueries({ queryKey: ["fan-chat-media", accountId, fanId], exact: false });
    void qc.invalidateQueries({ queryKey: ["fan-ppv-history", accountId, fanId], exact: false });
    void qc.invalidateQueries({ queryKey: ["last-purchases", accountId] });
    void qc.invalidateQueries({ queryKey: ofUserFullKey(accountId, fanId), exact: true });
    void qc.prefetchQuery({ ...ofUserQuery(accountId, fanId), staleTime: 0 });
    void qc.invalidateQueries({ queryKey: ["fan", accountId, fanId] });
  }, [qc]);
  // Outside the panel (a toast, Buys & tips, another window) the cap is told
  // under the Fan tabs strip, for a few seconds (story 49).
  const [tabsFull, setTabsFull] = useState(false);
  useEffect(() => {
    if (!tabsFull) return;
    const t = setTimeout(() => setTabsFull(false), TABS_FULL_NOTICE_MS);
    return () => clearTimeout(t);
  }, [tabsFull]);
  // Every other notification (toast, Buys & tips, one clicked in another
  // window or the desktop app) opens its Fan the same way
  // (lib/notificationLink). Until the Employee resolves no tab could be
  // stored, so those links load this window instead, and the arrival below
  // adds the tab.
  useEffect(() => fanTabsEmployeeKey === null ? undefined : setFanTabOpener((tab, { refresh }) => {
    if (handleOpenNotificationFan(tab) === "full") setTabsFull(true);
    if (refresh) refreshMoney(tab);
  }), [fanTabsEmployeeKey, handleOpenNotificationFan, refreshMoney]);
  // One from another window arrives as this Deep link with `?fanTab=<name>`:
  // its Thread is the link's, so add the Fan's tab once the Employee
  // resolves, then drop the param so a reload adds nothing.
  const fanTabParamReadRef = useRef(false);
  useEffect(() => {
    if (!deepLink || fanTabsEmployeeKey === null || fanTabParamReadRef.current) return;
    fanTabParamReadRef.current = true;
    const name = new URL(window.location.href).searchParams.get(FAN_TAB_PARAM);
    if (name === null) return;
    if (openFanTab({ ...deepLink, name }) === "full") setTabsFull(true);
    stripSearchParam(FAN_TAB_PARAM);
  }, [deepLink, fanTabsEmployeeKey, openFanTab]);

  // Empty the Thread: the Thread's Back, and ✕ on the last Fan tab.
  const clearSelection = useCallback(() => {
    setArrival(undefined);
    setSelected(null);
  }, []);

  // After ✕ on a Fan tab: open the tab the strip names (the last remaining),
  // or, with none, empty the Thread (messages.js:2577-2578).
  const handleClosedTab = useCallback((next: FanTab | null) => {
    if (next) handleActivateTab(next);
    else clearSelection();
  }, [handleActivateTab, clearSelection]);

  // The Fan tabs close rule runs in every window: from lg up the Fan tabs
  // strip runs it (and moves focus after a ✕); below lg, where the strip is
  // not mounted, the page does, so a tab another window closes moves this
  // Thread at phone width too (plan decision E, ticket 128).
  const activeTabKey = selected ? fanTabKey(selected.accountId, selected.fanId) : null;
  useFanTabsCloseRule({
    activeKey: activeTabKey,
    onClosed: handleClosedTab,
    enabled: !desktop,
  });

  // Infloww's shortcuts (gap 04 M17). Ctrl+W closes the open Fan's tab, and
  // the close rule above (or the strip's) opens the next one. It is claimed
  // even with no tab to close: on Windows the Electron menu's Ctrl+W would
  // close the window, and with it the app. Cmd/Ctrl+Shift+S flips SFW.
  const [, toggleSfw] = useSfw();
  useHotkeys([
    {
      keys: "ctrl+w",
      run: () => {
        if (activeTabKey !== null && fanTabsEmployeeKey !== null) closeFanTab(activeTabKey);
      },
    },
    { keys: "mod+shift+s", run: toggleSfw },
  ]);

  // One-shot `?refresh=media` on a Deep link: tip/purchase toasts and Buys &
  // tips rail rows append it because the fan just moved money, so this tab's
  // localStorage-rehydrated caches are stale by seconds. Invalidate the
  // THREAD too, not just the Fan insights set — the persisted ["messages"]
  // snapshot is what paints first, and a money event changes it (PPV flips
  // locked→purchased, ledger tip rows land) — `refreshMoney`. Queries mounted
  // now refetch at once; Fan insights' refetch when the pane opens.
  // Then strip the param so a plain reload doesn't re-fire. Must wait out the
  // persister's restore —
  // invalidating mid-restore would let the rehydrated snapshot land on top of
  // the fresh refetch.
  const isRestoring = useIsRestoring();
  const refreshFiredRef = useRef(false);
  useEffect(() => {
    if (isRestoring || refreshFiredRef.current) return;
    if (!deepLink) return;
    if (new URL(window.location.href).searchParams.get("refresh") !== "media") return;
    refreshFiredRef.current = true;
    refreshMoney(deepLink);
    stripSearchParam("refresh");
  }, [isRestoring, refreshMoney, deepLink]);

  // A Deep link scopes this window (the Fan List and the realtime event scope)
  // to its Creator without saving it, so the Employee's other windows keep
  // their scope, even an All Models one: the Clone's "scoped to one creator
  // (do not persist)". Once per link (the page memoizes `deepLink`); a switch
  // made after arrival is saved as in-app.
  useEffect(() => {
    if (deepLink) setScope({ kind: "model", accountId: deepLink.accountId }, { persist: false });
  }, [deepLink, setScope]);
  // The `account` search parameter (the Creator window URL,
  // `/messages-pro?account=<id>`). On the index route it scopes this
  // window to that Creator without saving it, as a Deep link does, and reopens
  // and activates its Creator tab if it was stored as closed. On a Deep link
  // route the link's Creator decides the scope, so the parameter applies only
  // when it names that Creator (reopening its tab). An id that is not one of
  // the Creator tabs' Creators is ignored and the window opens as it would
  // without it (messages.js:3416-3428). Read once, after the Creators and the
  // Employee key have resolved, since both the id check and the reopen need them.
  const creatorTabs = useCreatorTabs();
  const accountParamReadRef = useRef(false);
  useEffect(() => {
    if (accountParamReadRef.current || !creatorTabs.ready) return;
    accountParamReadRef.current = true;
    const id = new URL(window.location.href).searchParams.get("account");
    if (id === null || (deepLink && id !== deepLink.accountId)) return;
    const wasClosed = creatorTabs.closed.some((a) => a.id === id);
    if (!wasClosed && !creatorTabs.open.some((a) => a.id === id)) return;
    if (wasClosed) creatorTabs.reopen(id);
    setScope({ kind: "model", accountId: id }, { persist: false });
  }, [creatorTabs, deepLink, setScope]);
  // True until the scope reaches the Deep link's Creator. Until then it still
  // names the saved Creator, and the arrival selection must survive that.
  const scopeSettlingRef = useRef(!!deepLink);

  // Clear the selected chat when the new scope no longer covers it.
  // Unified ("all") keeps everything; switching to a different model
  // hides the surface so the user picks a fan from the new model's list.
  useEffect(() => {
    if (scopeSettlingRef.current) {
      if (!(scope.kind === "model" && scope.accountId === deepLink?.accountId)) return;
      scopeSettlingRef.current = false;
    }
    if (!selected) return;
    if (scope.kind === "model" && selected.accountId !== scope.accountId) {
      setSelected(null);
    }
  }, [scope, selected, deepLink]);

  // Background-warm the vault caches so the first VaultPicker open is
  // instant. Two waves, both tagged `X-Priority: background` so the
  // relay's per-account lane (4 total / 2 background slots, see
  // service/server.py `_priority_lane`) always keeps reserved slots for
  // a user click that lands mid-warm. Within an account, lists + first
  // page of media run in parallel. Across accounts, accounts also run
  // in parallel — lanes are per-account so they don't interfere, and
  // network is the only shared resource.
  //
  // Wave 1 (cheap, fires ~800ms after mount): vault-lists + vault-media
  //   first page. These are what VaultPicker reads on open. Together
  //   they cover the "click vault → grid is already there" case.
  //
  // Wave 2 (expensive, fires ~15s after mount): wall-media. This walks
  //   5 OF post pages per account and drives the blue "sent on wall"
  //   rings in the picker. The grid renders without it; rings just pop
  //   in when wave 2 lands. Delayed so it doesn't share bandwidth with
  //   wave 1 or with first-click traffic.
  //
  // If a user opens the picker between mount and wave 1 they pay the
  // OF cold cost once — but the relay lane reservation means their
  // call jumps ahead of anything still queued for background.
  useEffect(() => {
    if (accounts.length === 0) return;
    let cancelled = false;
    const BG = { priority: "background" as const };

    // Only warm the account you're actually viewing. Warming EVERY account on
    // Inbox mount fanned a burst of live-OF vault calls (lists + media + wall)
    // across the whole roster into the relay's shared thread pool. When the
    // proxy is flaky (OF calls hang to their timeout), that burst starves the
    // pool and the foreground chat fetches queue behind it — the app-wide lag.
    // In unified ("all") scope we skip the mount warm entirely and let the
    // VaultPicker warm lazily on first open, so nothing blocks user actions.
    const warmTargets =
      scope.kind === "model"
        ? accounts.filter((a) => a.id === scope.accountId)
        : [];
    if (warmTargets.length === 0) return;

    // Cheap idle gate so a quick bounce through Inbox doesn't fire the
    // warmup at all. requestIdleCallback (or rAF fallback) waits for the
    // route to actually be settled before scheduling the first wave —
    // prevents the prefetch fan-out from racing a same-tick navigate-away
    // to Home, which left Home's render queued behind in-flight vault
    // prefetches and surfaced as the dev "Rendering…" indicator stalling.
    // Wrap in arrows so the WebIDL methods keep their `window` receiver —
    // bare references throw "Illegal invocation" in some browsers.
    type IdleHandle = number;
    type IdleWin = Window & {
      requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
      cancelIdleCallback?: (h: number) => void;
    };
    const w = window as IdleWin;
    const hasRic = typeof w.requestIdleCallback === "function";
    const ric: (cb: () => void) => IdleHandle = hasRic
      ? (cb) => w.requestIdleCallback!(cb, { timeout: 2000 })
      : (cb) => window.setTimeout(cb, 0) as unknown as IdleHandle;
    const cic: (h: IdleHandle) => void = hasRic && typeof w.cancelIdleCallback === "function"
      ? (h) => w.cancelIdleCallback!(h)
      : (h) => window.clearTimeout(h as unknown as number);

    const warmAccount = async (aid: string) => {
      if (cancelled) return;
      await Promise.all([
        qc.prefetchQuery({
          queryKey: ["vault-lists", aid],
          // Shared paginating fetcher — a bare limit=50 fetch here would
          // poison the picker's cache with a truncated folder list.
          queryFn: () => fetchAllVaultLists({ accountId: aid, ...BG }),
          staleTime: 5 * 60 * 1000,
        }).catch(() => {}),
        qc.prefetchInfiniteQuery({
          queryKey: ["vault-media", aid, "all", null],
          initialPageParam: 0,
          queryFn: () =>
            relay.get(
              "/api/of/v2/vault/media?limit=24&offset=0&type=all",
              { accountId: aid, ...BG },
            ),
          staleTime: 60_000,
        }).catch(() => {}),
      ]);
    };

    const warmWallMedia = async (aid: string) => {
      if (cancelled) return;
      await qc.prefetchQuery({
        queryKey: ["wall-media", aid],
        queryFn: () =>
          relay.get(
            `/admin/vault/wall-media?account_id=${encodeURIComponent(aid)}`,
            BG,
          ),
        staleTime: 60 * 60 * 1000,
      }).catch(() => {});
    };

    // Wave 1 deferred behind an idle callback chained off a longer timeout.
    // Was 800ms — bumped to 1500ms because a user who clicks Inbox and
    // immediately clicks Home (or any tab) within a second shouldn't pay
    // the prefetch cost at all. The idle wait then yields another frame
    // so we don't slam the network mid-route-transition.
    let r1: IdleHandle | null = null;
    let r2: IdleHandle | null = null;
    const t1 = window.setTimeout(() => {
      if (cancelled) return;
      r1 = ric(() => {
        if (cancelled) return;
        void Promise.all(warmTargets.map((a) => warmAccount(a.id)));
      });
    }, 1500);

    const t2 = window.setTimeout(() => {
      if (cancelled) return;
      r2 = ric(() => {
        if (cancelled) return;
        void Promise.all(warmTargets.map((a) => warmWallMedia(a.id)));
      });
    }, 15_000);

    return () => {
      cancelled = true;
      window.clearTimeout(t1);
      window.clearTimeout(t2);
      if (r1 != null) cic(r1);
      if (r2 != null) cic(r2);
    };
  }, [accounts, qc, scope]);

  // Below lg (1024px): one pane at a time — list → thread (header "Back"
  // returns to the list) → fan insights as a slide-over (header "Fan
  // insights", Escape or backdrop closes). Below lg the Window header's Creator
  // tabs hide, so a creator select (`ScopeSelect`) tops the Fan List (the top
  // bar has no model filter), and the list ↔ thread swap is
  // driven by `selected`. lg+ is one flex row, the Clone's `.body`: the Fan
  // List (`MP.panes.fanList`), then the Thread taking the rest and Fan
  // insights (`MP.panes.insights`), both inside ChatSurface. Each pane root
  // carries `data-mp-pane` for the harness. The Fan List draws no edge of its
  // own: its pane draws the right border at every width. lg rather than md is
  // intentional: landscape phones (~956px) and 768px tablets are too cramped
  // for list + thread + insights.
  // The root is the Infloww palette (ADR-0010): every route that renders
  // Messages Pro (index, Deep link, Pop-out window) draws in Infloww's colours.
  return (
    <InflowwPalette className={cn(MP.panes.root, "h-chat flex flex-col overflow-hidden")}>
      {desktop && <WindowHeader />}
      {desktop && <FanTabsRow openFan={selected} onActivate={handleActivateTab} onClosed={handleClosedTab} onHome={clearSelection} />}
      {tabsFull && (
        <div role="status" className="shrink-0 px-3 py-1 border-b border-border text-xs text-warn">{FAN_TABS_FULL_LABEL}</div>
      )}
      {!desktop && !selected && (
        <div className="shrink-0 px-2 py-1.5 border-b border-[var(--inf-rule,var(--color-border))]">
          <ScopeSelect accounts={accounts} pickAll={pickAll} />
        </div>
      )}
      <div className="flex-1 min-h-0 lg:flex">
        <div data-mp-pane="fan-list" className={cn(
          MP.panes.fanList, "min-h-0 h-full lg:block border-[var(--inf-rule,var(--color-border))]",
          selected ? "hidden" : "block",
        )}>
          <FanList
            selected={selected}
            onSelect={handleSelect}
            onlineOnly={onlineOnly}
            onlineIds={onlineIds}
            actions={(
              <FanListButtons
                onlineOnly={onlineOnly}
                onToggleOnline={() => setOnlineOnly((on) => !on)}
                onOpenFan={handleOpenNotificationFan}
                onlineListFailed={onlineListFailed}
              />
            )}
          />
        </div>
        {selected ? (
          <ChatSurface
            key={`${selected.accountId}:${selected.fanId}`}
            accountId={selected.accountId}
            fanId={selected.fanId}
            chat={arrivalChat || selected.chat}
            insightsOpenAtStart={!arrival}
            onBack={clearSelection}
          />
        ) : (
          <ThreadEmptyState />
        )}
      </div>
    </InflowwPalette>
  );
}

/** Drop `name` from the URL, keeping every other parameter and the hash. The
 *  state argument is `null`, not `window.history.state`: Next's patched
 *  replaceState skips its router sync for state carrying its `__NA` marker,
 *  and an unsynced router would write the parameter back on its next commit.
 *  With `null` it copies its internal state and dispatches a restore, and the
 *  address bar still changes synchronously. */
function stripSearchParam(name: string) {
  const url = new URL(window.location.href);
  if (!url.searchParams.has(name)) return;
  url.searchParams.delete(name);
  const qs = url.searchParams.toString();
  window.history.replaceState(null, "", url.pathname + (qs ? `?${qs}` : "") + url.hash);
}

/** The minimum chat a Deep link's Thread needs before the Fan List has its
 *  row: the Fan's id plus whatever the profile lookup found. canSendMessage
 *  is left unset; if OnlyFans blocks the chat, the Composer surfaces the
 *  reason on first send. */
function deepLinkChat(link: MessagesProDeepLink, profile: OFUserMini | null | undefined): OFChatItem {
  return {
    withUser: {
      id: link.fanId,
      name: profile?.name,
      username: profile?.username,
      avatar: profile?.avatar ?? null,
      customNickname: profile?.customNickname ?? null,
    },
    __accountId: link.accountId,
    hasUnread: false,
  };
}
