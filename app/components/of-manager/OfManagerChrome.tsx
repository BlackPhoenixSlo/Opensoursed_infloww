"use client";


import { usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Maximize, PanelRight, RotateCw } from "lucide-react";

import { CreatorColumn, PALETTE } from "@/components/of-manager/CreatorColumn";
import { AutoPickContext, standInPick } from "@/lib/ofMirrorProfile";
import { liveSession } from "@/lib/sessionConnectivity";
import { popoutReady } from "@/components/of-manager/popoutReady";
import { FanDrawer } from "@/components/chat/FanDrawer";
import { InflowwPalette } from "@/components/chat/InflowwPalette";
import { TemplatePicker } from "@/components/chat/TemplatePicker";

import { CreatorsAction, NoCreators } from "@/components/shell/NoCreators";
import { ScopeSelect } from "@/components/shell/ScopeSelect";
import { EmptyState } from "@/components/ui/infloww";
import { usePageCreator } from "@/contexts/PageCreatorContext";
import { ScopeOverride, useScope, WatcherScope } from "@/contexts/ScopeContext";
import { ofManagerWatcher, useAccounts, useOfManagerAccounts, usePlatformAccounts, useWatcherAccounts } from "@/hooks/useAccounts";
import { findFanChatRow } from "@/hooks/useInboxRealtime";
import { useIsDesktop } from "@/hooks/useIsDesktop";
import { fanIdFromParam, type FanId } from "@/lib/fanId";
import { findNavLink, platformOfPath } from "@/lib/nav";
import { DEFAULT_PLATFORM, foreignCreator, type Platform } from "@/lib/platform";
import { applyScript, type PickedScript } from "@/lib/ofMirrorChat";
import { OF_INSIGHTS_ATTR } from "@/lib/ofMirrorChrome";
import { mirrorQuery } from "@/lib/ofMirrorData";
import { chatPath } from "@/lib/ofMirrorDataQueries";
import { type OFChatItem } from "@/lib/relay";
import { InfoTip } from "@/components/ui/InfoTip";

function localOffsetLabel(): string {
  const mins = -new Date().getTimezoneOffset();
  const abs = Math.abs(mins);
  return `UTC${mins < 0 ? "-" : "+"}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
}
const noSubscribe = () => () => {};

const INSIGHTS_KEY = "oi:ofm:insights";
const insightsListeners = new Set<() => void>();
function subscribeInsights(cb: () => void) {
  insightsListeners.add(cb);
  return () => { insightsListeners.delete(cb); };
}
const insightsShown = () => localStorage.getItem(INSIGHTS_KEY) !== "0";
function showInsights(on: boolean) {
  localStorage.setItem(INSIGHTS_KEY, on ? "1" : "0");
  insightsListeners.forEach((f) => f());
}

function useChatItem(accountId: string | null, fanId: FanId | null, fan: string | null): OFChatItem | null {
  const qc = useQueryClient();
  const read = useQuery(mirrorQuery<OFChatItem>(accountId, fan != null && fanId != null ? chatPath(fan) : null, true)).data;
  const subscribe = useCallback((cb: () => void) => qc.getQueryCache().subscribe(cb), [qc]);
  const row = useSyncExternalStore(
    subscribe,
    () => (accountId && fanId != null ? findFanChatRow(qc, accountId, fanId) : null),
    () => null,
  );
  const bare = useMemo(() => (fanId == null ? null : { withUser: { id: fanId } }), [fanId]);
  return row ?? (read?.withUser ? read : null) ?? bare;
}

export function OfManagerChrome({ children }: { children: React.ReactNode }) {
  const accountsQ = useAccounts();
  const watchers = useWatcherAccounts();
  const watcherIds = useMemo(() => watchers.map((w) => w.id), [watchers]);
  const pickable = useMemo(() => watchers.filter(ofManagerWatcher).map((w) => w.id), [watchers]);
  return (
    <WatcherScope watcherIds={watcherIds} pickable={pickable} loaded={accountsQ.isSuccess}>
      <OneCreator>
        <Chrome>{children}</Chrome>
      </OneCreator>
    </WatcherScope>
  );
}

function routePlatform(pathname: string): Platform {
  return platformOfPath(pathname) ?? DEFAULT_PLATFORM;
}

function OneCreator({ children }: { children: React.ReactNode }) {
  const { accountId } = useScope();
  const platform = routePlatform(usePathname() ?? "/");
  const creators = usePlatformAccounts(platform);
  const known = useAccounts().data?.accounts;
  const foreign = foreignCreator(known, accountId, platform);
  const auto = accountId && !foreign ? null : standInPick(creators);
  const autoPick = useMemo(() => ({ platform, accountId: auto }), [platform, auto]);
  return (
    <AutoPickContext.Provider value={autoPick}>
      <ScopeOverride accountId={auto}>{children}</ScopeOverride>
    </AutoPickContext.Provider>
  );
}

function Chrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  const section = pathname.split("/")[2] ?? "";
  const title = findNavLink(`/of-manager/${section}`)?.label ?? "OF Manager";
  const tz = useSyncExternalStore(noSubscribe, localOffsetLabel, () => null);
  const accountsQ = useAccounts();
  const accounts = useOfManagerAccounts();
  const noCreators = accountsQ.isSuccess && accounts.length === 0;
  const { scope, setScope } = useScope();
  usePageCreator(scope.kind === "model" ? scope.accountId : null);
  const known = accountsQ.data;
  const platform = routePlatform(pathname);
  const popped = useRef(false);
  useEffect(() => {
    if (popped.current) return;
    const knownIds = [...(known?.accounts ?? []), ...(known?.watchers ?? [])].map((a) => a.id);
    const id = new URL(window.location.href).searchParams.get("account");
    if (!popoutReady(id, knownIds, accountsQ.isSuccess)) return;
    popped.current = true;
    const foreign = foreignCreator(known?.accounts, id, platform);
    if (id && !foreign) setScope({ kind: "model", accountId: id }, { persist: false });
  }, [setScope, known, accountsQ.isSuccess, platform]);
  const scoped = scope.kind === "model" ? accounts.find((a) => a.id === scope.accountId) : undefined;
  const sessionGone = !!scoped && !liveSession(scoped);
  const viewTools = !!scoped && !sessionGone;
  const [viewKey, setViewKey] = useState(0);
  const lastReload = useRef(0);
  const reload = useCallback(() => {
    const now = Date.now();
    if (now - lastReload.current < 2000) return;
    lastReload.current = now;
    setViewKey((k) => k + 1);
  }, []);
  const viewRef = useRef<HTMLDivElement>(null);
  const fan = useSearchParams()?.get("chat") ?? null;
  const fanId = fanIdFromParam(fan);
  const onChat = pathname === "/of-manager/messages/chat" && viewTools && scoped.role !== "watcher";
  const chat = useChatItem(scoped?.id ?? null, onChat ? fanId : null, onChat ? fan : null);
  const insights = viewTools && chat ? { accountId: scoped.id, fanId: chat.withUser.id, chat } : null;
  const desktop = useIsDesktop();
  const pinnedOn = useSyncExternalStore(subscribeInsights, insightsShown, () => true);
  const [sheet, setSheet] = useState(false);
  const insightsOn = desktop ? pinnedOn : sheet;
  const pinned = !!insights && desktop && pinnedOn;
  useEffect(() => {
    const view = viewRef.current;
    if (!view || !pinned) return;
    // Mid-swap a frame's document can have no <html> yet; its load marks it.
    const mark = (on: boolean) =>
      view.querySelectorAll("iframe").forEach((f) => f.contentDocument?.documentElement?.toggleAttribute(OF_INSIGHTS_ATTR, on));
    const onLoad = () => mark(true);
    mark(true);
    // a frame's load does not bubble; capture sees each page's
    view.addEventListener("load", onLoad, true);
    return () => {
      view.removeEventListener("load", onLoad, true);
      mark(false);
    };
  }, [pinned, viewKey]);
  const pick = (t: PickedScript) => {
    if (!insights || fan == null) return;
    applyScript(window.sessionStorage, insights.accountId, fan, t, viewRef.current?.querySelector("iframe")?.contentDocument ?? null);
  };

  const btn = "w-6 h-6 grid place-items-center rounded text-[var(--ofm-fg)] hover:opacity-80";
  return (
    <div className="ofm flex flex-col" data-testid="of-manager-chrome">
      <style>{PALETTE}</style>
      <div className="h-12 shrink-0 flex items-center justify-between px-6 bg-[var(--ofm-nav)] border-b border-[var(--ofm-line)] box-border">
        <div className="flex items-center min-w-0 select-none">
          <h1 className="text-base font-medium text-fg truncate">{title}</h1>
          {accounts.length > 0 && (
            <ScopeSelect accounts={accounts} onPicked={() => setViewKey((k) => k + 1)} className="ml-3 lg:hidden" />
          )}
          {tz && (
            <span className={`mx-4 flex items-center gap-2 text-base text-fg-dim tabular-nums${insights ? " max-sm:hidden" : ""}`}>
              {tz}
              <InfoTip text="The time zone of this computer" iconClassName="w-4 h-4" />
            </span>
          )}
        </div>
        {viewTools && (
          <div className="shrink-0 flex items-center gap-6">
            {insights && !desktop && (
              <InflowwPalette className="contents">
                <TemplatePicker accountId={insights.accountId} onPick={pick} messagesPro />
              </InflowwPalette>
            )}
            {insights && (
              <button
                type="button"
                className="w-7 h-7 grid place-items-center rounded text-[var(--ofm-fg)] hover:opacity-80 aria-pressed:text-[var(--ofm-blue)]"
                title="Fan insights"
                aria-label="Fan insights"
                aria-pressed={insightsOn}
                onClick={() => (desktop ? showInsights(!pinnedOn) : setSheet((v) => !v))}
              >
                <PanelRight aria-hidden className="w-5 h-5" />
              </button>
            )}
            <button
              type="button"
              className={btn}
              title="Pop out"
              aria-label="Pop out"
              onClick={() => window.open(`${pathname}?account=${encodeURIComponent(scoped.id)}`, "_blank", "popup")}
            >
              <ExternalLink aria-hidden className="w-5 h-5" />
            </button>
            <button type="button" className={btn} title="Fullscreen" aria-label="Fullscreen" onClick={() => void viewRef.current?.requestFullscreen?.()}>
              <Maximize aria-hidden className="w-5 h-5" />
            </button>
            <button type="button" className={btn} title="Reload" aria-label="Reload" onClick={reload}>
              <RotateCw aria-hidden className="w-5 h-5" />
            </button>
          </div>
        )}
      </div>
      <div className="flex" style={{ ["--shell-top" as string]: "calc(var(--chrome-top) + 48px)" }}>
        <CreatorColumn accounts={accounts} onPicked={() => setViewKey((k) => k + 1)} />
        <div ref={viewRef} key={viewKey} className="relative flex-1 min-w-0 h-chat bg-[var(--ofm-nav)]">
          {noCreators ? <NoCreators className="h-full" /> : sessionGone ? <SessionGone /> : children}
          {insights && !desktop && sheet && (
            <InflowwPalette className="contents">
              <FanDrawer open onClose={() => setSheet(false)} onComposeWith={pick} {...insights} />
            </InflowwPalette>
          )}
          {pinned && insights && (
            <InflowwPalette className="absolute inset-y-0 right-0 flex w-70 flex-col">
              <div className="shrink-0 flex items-center gap-2 px-3 py-2 border-l border-b border-[var(--inf-rule,var(--color-border))]">
                <TemplatePicker accountId={insights.accountId} onPick={pick} messagesPro />
              </div>
              <div className="flex-1 min-h-0 flex">
                <FanDrawer pinned open onClose={() => showInsights(false)} onComposeWith={pick} {...insights} />
              </div>
            </InflowwPalette>
          )}
        </div>
      </div>
    </div>
  );
}

function SessionGone() {
  return (
    <div className="h-full flex items-center justify-center px-6" data-testid="of-session-gone">
      <EmptyState
        kind="creator"
        text="This creator's OnlyFans connection has expired."
        textClassName="mt-4 mb-1.5 text-base leading-6 font-medium text-fg"
        action={<CreatorsAction label="Go To Creators Management" />}
      />
    </div>
  );
}
