"use client";

/**
 * OF Manager's chrome around the mirrored page, as Infloww's (docs/infloww-of-manager-rea.md §1.5, §1.7): a 48px page
 * header ("Home  UTC+02:00 (i)", fullscreen and reload on the right) over a 192px creator column (Search, refresh,
 * "All creators", one row per creator with its avatar, online dot, OF notification count and unread chats) and the OF view.
 * A row picks that creator (ScopeContext) and reloads the OF view for it; below lg the column hides and a creator
 * select in the page header picks instead (the top bar has no creator filter). With no
 * creators the view gives way to Infloww's `OfNotHaveModel`; a picked creator whose OF session is dead or missing
 * gets Infloww's `page-error` placeholder over the view instead of the mirror. "Pop out" opens this page as a window
 * of its own on the picked creator (`?account=<id>`, which scopes that window without saving it, as Messages Pro's
 * Creator window URL does), so each creator's OF page can sit in its own window.
 * On an open OF chat (`/of-manager/messages/chat?chat=<fanId>`, one creator) Infloww's 280px Fan insights column sits
 * over the view's right edge (the chat page leaves it the room, so OF keeps its wide layout): Messages Pro's FanDrawer,
 * pinned, in Infloww's palette, with the Scripts picker (TemplatePicker) over it: a picked script, or an unsold PPV's
 * "Send to chat", goes on the mirror's Chat draft (applyScript), shown in OF's composer in the frame. Below lg the
 * header's Fan insights button opens it as its slide-over instead. It is the chat's one Fan insights mount.
 */

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Info, Maximize, PanelRight, RotateCw } from "lucide-react";

import { CreatorColumn, PALETTE, liveSession } from "@/components/of-manager/CreatorColumn";
import { FanDrawer } from "@/components/chat/FanDrawer";
import { InflowwPalette } from "@/components/chat/InflowwPalette";
import { TemplatePicker } from "@/components/chat/TemplatePicker";

import { ScopeSelect } from "@/components/shell/ScopeSelect";
import { useGrantedPages } from "@/components/shell/useGrantedPages";
import { EmptyState } from "@/components/ui/infloww";
import { useScope } from "@/contexts/ScopeContext";
import { useAccounts, useActiveAccounts } from "@/hooks/useAccounts";
import { findFanChatRow } from "@/hooks/useInboxRealtime";
import { useIsDesktop } from "@/hooks/useIsDesktop";
import { fanIdFromParam, type FanId } from "@/lib/fanId";
import { deniedPage, findNavLink } from "@/lib/nav";
import { applyScript, type PickedScript } from "@/lib/ofMirrorChat";
import { OF_INSIGHTS_ATTR } from "@/lib/ofMirrorChrome";
import { chatPath, mirrorQuery } from "@/lib/ofMirrorData";
import { type OFChatItem } from "@/lib/relay";

/** "UTC+02:00": this computer's offset (Infloww's OF Manager shows the local zone, not the Agency's). */
function localOffsetLabel(): string {
  const mins = -new Date().getTimezoneOffset();
  const abs = Math.abs(mins);
  return `UTC${mins < 0 ? "-" : "+"}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
}
const noSubscribe = () => () => {};

/** The Fan insights column's shown / hidden, kept across loads; open unless hidden. */
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

/** The open chat's row from the chat list the mirror reads (Messages Pro's ["chats", ...] cache), else the chat the
 *  mirror's page reads (`fan`, the chat's `?chat=`: the same query as useOfChat's, so no second request), else the fan
 *  id alone. */
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
  const pathname = usePathname() ?? "";
  const section = pathname.split("/")[2] ?? "";
  const title = findNavLink(`/of-manager/${section}`)?.label ?? "OF Manager";
  const tz = useSyncExternalStore(noSubscribe, localOffsetLabel, () => null);
  const accountsQ = useAccounts();
  const accounts = useActiveAccounts();
  const noCreators = accountsQ.isSuccess && accounts.length === 0;
  const { scope, setScope } = useScope();
  // A Pop-out window's `?account=<id>`: this window's creator, not saved, so the opener keeps its own.
  useEffect(() => {
    const id = new URL(window.location.href).searchParams.get("account");
    if (id) setScope({ kind: "model", accountId: id }, { persist: false });
  }, [setScope]);
  const scoped = scope.kind === "model" ? accounts.find((a) => a.id === scope.accountId) : undefined;
  const sessionGone = !!scoped && !liveSession(scoped);
  // OfMessageToolbar: fullscreen and reload only for one creator with a live session; reload throttled to 2s.
  const viewTools = !!scoped && !sessionGone;
  // Bumped by reload and by picking a creator: a fresh OF view (Infloww recreates its BrowserView for the creator).
  const [viewKey, setViewKey] = useState(0);
  const lastReload = useRef(0);
  const reload = useCallback(() => {
    const now = Date.now();
    if (now - lastReload.current < 2000) return;
    lastReload.current = now;
    setViewKey((k) => k + 1);
  }, []);
  const viewRef = useRef<HTMLDivElement>(null);
  // Fan insights: an open chat of one creator with a live session (no chat, All creators: none).
  const fan = useSearchParams()?.get("chat") ?? null;
  const fanId = fanIdFromParam(fan);
  const onChat = pathname === "/of-manager/messages/chat" && viewTools;
  const chat = useChatItem(scoped?.id ?? null, onChat ? fanId : null, onChat ? fan : null);
  const insights = viewTools && chat ? { accountId: scoped.id, fanId: chat.withUser.id, chat } : null;
  const desktop = useIsDesktop();
  const pinnedOn = useSyncExternalStore(subscribeInsights, insightsShown, () => true);
  const [sheet, setSheet] = useState(false);
  const insightsOn = desktop ? pinnedOn : sheet;
  const pinned = !!insights && desktop && pinnedOn;
  // Infloww mounts the column inside OF's page (`.b-chats__conversations`), so OF's viewport keeps the view's width: the
  // frame keeps it here too, the column lies over its right 280px and the page, marked, leaves that room.
  useEffect(() => {
    const view = viewRef.current;
    if (!view || !pinned) return;
    const mark = (on: boolean) =>
      // Mid-swap a frame's document can have no <html> yet; its load marks it.
      view.querySelectorAll("iframe").forEach((f) => f.contentDocument?.documentElement?.toggleAttribute(OF_INSIGHTS_ATTR, on));
    const onLoad = () => mark(true);
    mark(true);
    view.addEventListener("load", onLoad, true); // a frame's load does not bubble; capture sees each page's
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
          {/* Below lg the creator column hides: this select picks the creator instead. */}
          {accounts.length > 0 && (
            <ScopeSelect accounts={accounts} onPicked={() => setViewKey((k) => k + 1)} className="ml-3 lg:hidden" />
          )}
          {tz && (
            <span className="mx-4 flex items-center gap-2 text-base text-fg-dim tabular-nums">
              {tz}
              <span title="The time zone of this computer"><Info aria-hidden className="w-4 h-4" /></span>
            </span>
          )}
        </div>
        {viewTools && (
          <div className="flex items-center gap-6">
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
      {/* `.h-chat` below subtracts this header too. */}
      <div className="flex" style={{ ["--shell-top" as string]: "calc(var(--chrome-top) + 48px)" }}>
        <CreatorColumn accounts={accounts} onPicked={() => setViewKey((k) => k + 1)} />
        <div ref={viewRef} key={viewKey} className="relative flex-1 min-w-0 h-chat bg-[var(--ofm-nav)]">
          {noCreators ? <NoCreators /> : sessionGone ? <SessionGone /> : children}
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

/** Whether this session may open Creators Management; Infloww shows `no-OF-account-error-text` to one that may not. */
function useCanOpenCreators(): boolean {
  return !deniedPage("/creators", useGrantedPages());
}

const NO_PERMISSION = "Unfortunately, you don't have permission for this page. Please contact the administrator.";
const PRIMARY = "h-8 px-[15px] grid place-items-center rounded-md bg-accent text-white text-base hover:opacity-90";

/** The link to Creators Management, or Infloww's no-permission line for a session that may not open it. */
function CreatorsAction({ label }: { label: string }) {
  if (!useCanOpenCreators()) return <p className="max-w-[380px] text-err text-sm">{NO_PERMISSION}</p>;
  return <Link href="/creators" className={PRIMARY}>{label}</Link>;
}

/** Infloww's OfNotHaveModel: the 100px `data` art, 16px, the bundle's three-line copy (16/24 T1), 16px, the button. */
function NoCreators() {
  return (
    <div className="h-full flex items-center justify-center px-6">
      <EmptyState
        kind="data"
        text={<>You have not yet tied a creator, if you need to bind<br />one, you can bind on the “Creators Management” page.</>}
        textClassName="mt-4 mb-1.5 max-w-[400px] text-base leading-6 font-medium text-fg"
        action={<CreatorsAction label="Link account" />}
      />
    </div>
  );
}

/** Infloww's BrowserView `page-error` for a picked creator with no live OF session. The copy is ours: Infloww's is
 *  remote i18n ("creator_account_connection_expired"), not in the bundle. */
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
