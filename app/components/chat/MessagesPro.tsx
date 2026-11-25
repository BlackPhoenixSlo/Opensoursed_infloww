"use client";


import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useIsRestoring, useQuery, useQueryClient } from "@tanstack/react-query";

import { FanList, type FanListSelection } from "@/components/chat/FanList";
import { FanListButtons } from "@/components/chat/FanListButtons";
import { ChatSurface } from "@/components/chat/ChatSurface";
import { FanTabsRow } from "@/components/chat/FanTabsRow";
import { InflowwPalette } from "@/components/chat/InflowwPalette";
import { initialMessagesProSelection, messagesProSelectionReducer } from "@/components/chat/messagesProSelection";
import { FAN_TABS_FULL_LABEL, fanTabKey, useFanTabs, useFanTabsCloseRule, type FanTab } from "@/components/chat/useFanTabs";
import { ThreadEmptyState } from "@/components/chat/ThreadEmptyState";
import { WindowHeader } from "@/components/chat/WindowHeader";
import { useCreatorTabs } from "@/components/chat/useCreatorTabs";
import { ScopeSelect } from "@/components/shell/ScopeSelect";
import { UNREAD_WARM_REUSE_MS } from "@/hooks/useUnreadMessagesPrefetch";
import { ofUserFullKey, ofUserNameKey, ofUserNameQuery, ofUserQuery, type OFUserName } from "@/hooks/useOFUser";
import { useOnlineSubscribers } from "@/hooks/useOnlineSubscribers";
import { fetchAllVaultLists } from "@/hooks/useVaultMedia";
import { usePlatformAccounts } from "@/hooks/useAccounts";
import { usePickAllModels } from "@/hooks/usePickAllModels";
import { useSfw } from "@/hooks/useBlurMode";
import { useHotkeys } from "@/hooks/useHotkeys";
import { keepChatEntry, useChatBackEntry } from "@/hooks/useChatBackEntry";
import { useIsDesktop } from "@/hooks/useIsDesktop";
import { usePageCreator } from "@/contexts/PageCreatorContext";
import { useScope } from "@/contexts/ScopeContext";
import { WINDOW_HEADER_ACTIONS } from "@/lib/chatUiSlots";
import { MP } from "@/lib/messagesPro";
import { FAN_TAB_PARAM, setFanTabOpener } from "@/lib/notificationLink";
import { cn } from "@/lib/utils";
import { relay, setRelayFocus, type OFChatItem, type OFUserMini } from "@/lib/relay";
import { sameUserId, type FanId } from "@/lib/fanId";

const TABS_FULL_NOTICE_MS = 8_000;

const headerActions = WINDOW_HEADER_ACTIONS.length
  ? <>{WINDOW_HEADER_ACTIONS.map((Action, i) => <Action key={i} />)}</>
  : undefined;

export interface MessagesProDeepLink {
  accountId: string;
  fanId: FanId;
}

export function MessagesPro({ deepLink }: { deepLink?: MessagesProDeepLink } = {}) {
  const [{ selected, fromLink }, dispatchSelection] = useReducer(
    messagesProSelectionReducer,
    deepLink,
    (link) => initialMessagesProSelection(link ? { ...link, chat: deepLinkChat(link, undefined) } : null),
  );
  const arrival = fromLink ? deepLink : undefined;
  const [onlineOnly, setOnlineOnly] = useState(false);
  const desktop = useIsDesktop();
  const qc = useQueryClient();
  const accounts = usePlatformAccounts();
  const { pickAll } = usePickAllModels();
  const { scope, setScope } = useScope();
  usePageCreator(scope.kind === "model" ? scope.accountId : null);
  const focusAccountId = selected?.accountId ?? (scope.kind === "model" ? scope.accountId : null);
  useEffect(() => {
    setRelayFocus(focusAccountId);
    return () => setRelayFocus(null);
  }, [focusAccountId]);

  const onlineAccountId = onlineOnly && scope.kind === "model" ? scope.accountId : null;
  const onlineListQ = useOnlineSubscribers(onlineAccountId);
  const onlineIds = onlineListQ.data?.ids;
  const onlineListFailed = onlineListQ.isError;

  const profileQ = useQuery({
    ...ofUserNameQuery(deepLink?.accountId ?? "", deepLink?.fanId ?? ""),
    enabled: !!deepLink,
    refetchOnWindowFocus: false,
  });
  const arrivalChat = useMemo(
    () => arrival && deepLinkChat(arrival, profileQ.data),
    [arrival, profileQ.data],
  );

  const handleSelect = useCallback((sel: FanListSelection) => {
    if (deepLink && !(sel.accountId === deepLink.accountId && sameUserId(sel.fanId, deepLink.fanId))) {
      // drop `msg` before the next Thread mounts: its effect would page back through up to six live OF calls
      stripSearchParam("msg");
    }
    dispatchSelection({ type: "select", sel });
  }, [deepLink]);

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

  const { open: openFanTab, close: closeFanTab, employeeKey: fanTabsEmployeeKey } = useFanTabs();
  const handleOpenNotificationFan = useCallback((tab: FanTab) => {
    const result = fanTabsEmployeeKey === null ? null : openFanTab(tab);
    handleActivateTab(tab);
    return result;
  }, [fanTabsEmployeeKey, openFanTab, handleActivateTab]);
  const refreshMoney = useCallback(({ accountId, fanId }: { accountId: string; fanId: FanId }) => {
    void qc.invalidateQueries({ queryKey: ["messages", accountId, fanId] });
    void qc.invalidateQueries({ queryKey: ["fan-chat-media", accountId, fanId], exact: false });
    void qc.invalidateQueries({ queryKey: ["fan-ppv-history", accountId, fanId], exact: false });
    void qc.invalidateQueries({ queryKey: ["last-purchases", accountId] });
    void qc.invalidateQueries({ queryKey: ofUserFullKey(accountId, fanId), exact: true });
    void qc.prefetchQuery({ ...ofUserQuery(accountId, fanId), staleTime: 0 });
    void qc.invalidateQueries({ queryKey: ["fan", accountId, fanId] });
  }, [qc]);
  const [tabsFull, setTabsFull] = useState(false);
  useEffect(() => {
    if (!tabsFull) return;
    const t = setTimeout(() => setTabsFull(false), TABS_FULL_NOTICE_MS);
    return () => clearTimeout(t);
  }, [tabsFull]);
  useEffect(() => fanTabsEmployeeKey === null ? undefined : setFanTabOpener((tab, { refresh }) => {
    if (handleOpenNotificationFan(tab) === "full") setTabsFull(true);
    if (refresh) refreshMoney(tab);
  }), [fanTabsEmployeeKey, handleOpenNotificationFan, refreshMoney]);
  const fanTabParamReadRef = useRef(false);
  useEffect(() => {
    if (!deepLink || fanTabsEmployeeKey === null || fanTabParamReadRef.current) return;
    fanTabParamReadRef.current = true;
    const name = new URL(window.location.href).searchParams.get(FAN_TAB_PARAM);
    if (name === null) return;
    if (openFanTab({ ...deepLink, name }) === "full") setTabsFull(true);
    stripSearchParam(FAN_TAB_PARAM);
  }, [deepLink, fanTabsEmployeeKey, openFanTab]);

  const clearSelection = useCallback(() => {
    dispatchSelection({ type: "clear" });
  }, []);
  const backToList = useChatBackEntry(!desktop, selected !== null, clearSelection);

  const handleClosedTab = useCallback((next: FanTab | null) => {
    if (next) handleActivateTab(next);
    else clearSelection();
  }, [handleActivateTab, clearSelection]);

  const activeTabKey = selected ? fanTabKey(selected.accountId, selected.fanId) : null;
  useFanTabsCloseRule({
    activeKey: activeTabKey,
    onClosed: handleClosedTab,
    enabled: !desktop,
  });

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

  const isRestoring = useIsRestoring();
  const refreshFiredRef = useRef(false);
  useEffect(() => {
    // invalidating mid-restore would let the rehydrated snapshot land on top of the fresh refetch
    if (isRestoring || refreshFiredRef.current) return;
    if (!deepLink) return;
    if (new URL(window.location.href).searchParams.get("refresh") !== "media") return;
    refreshFiredRef.current = true;
    refreshMoney(deepLink);
    stripSearchParam("refresh");
  }, [isRestoring, refreshMoney, deepLink]);

  useEffect(() => {
    if (deepLink) setScope({ kind: "model", accountId: deepLink.accountId }, { persist: false });
  }, [deepLink, setScope]);
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
  const scopeSettlingRef = useRef(!!deepLink);

  useEffect(() => {
    if (scopeSettlingRef.current) {
      if (!(scope.kind === "model" && scope.accountId === deepLink?.accountId)) return;
      scopeSettlingRef.current = false;
    }
    if (!selected) return;
    if (scope.kind === "model" && selected.accountId !== scope.accountId) {
      dispatchSelection({ type: "clear" });
    }
  }, [scope, selected, deepLink]);

  useEffect(() => {
    if (accounts.length === 0) return;
    let cancelled = false;
    const BG = { priority: "background" as const };

    const warmTargets =
      scope.kind === "model"
        ? accounts.filter((a) => a.id === scope.accountId)
        : [];
    if (warmTargets.length === 0) return;

    type IdleHandle = number;
    type IdleWin = Window & {
      requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
      cancelIdleCallback?: (h: number) => void;
    };
    const w = window as IdleWin;
    const hasRic = typeof w.requestIdleCallback === "function";
    // arrows keep the `window` receiver: bare WebIDL refs throw "Illegal invocation" in some browsers
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

  return (
    <InflowwPalette className={cn(MP.panes.root, "h-chat flex flex-col overflow-hidden")}>
      {desktop && <WindowHeader actions={headerActions} />}
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
            warmWindowMs={UNREAD_WARM_REUSE_MS}
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
            prefetchWindowMs={UNREAD_WARM_REUSE_MS}
            onBack={backToList}
          />
        ) : (
          <ThreadEmptyState />
        )}
      </div>
    </InflowwPalette>
  );
}

function stripSearchParam(name: string) {
  const url = new URL(window.location.href);
  if (!url.searchParams.has(name)) return;
  url.searchParams.delete(name);
  const qs = url.searchParams.toString();
  // not window.history.state: Next's patched replaceState skips its router sync for state with `__NA`, and the param gets written back
  window.history.replaceState(keepChatEntry(), "", url.pathname + (qs ? `?${qs}` : "") + url.hash);
}

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
