"use client";

/**
 * OF Manager's chrome around the mirrored page, as Infloww's (docs/infloww-of-manager-rea.md §1.5, §1.7): a 48px page
 * header ("Home  UTC+02:00 (i)", fullscreen and reload on the right) over a 192px creator column (Search, refresh,
 * "All creators", one row per creator with its avatar, online dot, OF notification count and unread chats) and the OF view.
 * OF Manager's "All creators" select is Infloww's GroupSelect: All creators, then each Tag (a Tag is Infloww's creator
 * group, useCreatorProfiles), which narrows the rows to the creators holding it. A chatter is refused the Tags' blob,
 * so it offers All creators alone.
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
import { skipToken, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, ChevronDown, ChevronsLeft, ChevronsRight, ExternalLink, Info, Maximize, PanelRight, RotateCw, Search } from "lucide-react";

import { FanDrawer } from "@/components/chat/FanDrawer";
import { InflowwPalette } from "@/components/chat/InflowwPalette";
import { TemplatePicker } from "@/components/chat/TemplatePicker";

import { useGrantedPages } from "@/components/shell/useGrantedPages";
import { AccountAvatarPicture } from "@/components/ui/AccountAvatarPicture";
import { EmptyState } from "@/components/ui/infloww";
import { ScopeSelect } from "@/components/shell/ScopeSelect";
import { useScope } from "@/contexts/ScopeContext";
import { useCreatorProfiles } from "@/lib/creatorProfiles";
import { useAccounts, useActiveAccounts } from "@/hooks/useAccounts";
import { findFanChatRow } from "@/hooks/useInboxRealtime";
import { useIsDesktop } from "@/hooks/useIsDesktop";
import { useRosterCounts } from "@/hooks/useRosterCounts";
import { fanIdFromParam, type FanId } from "@/lib/fanId";
import { deniedPage, findNavLink } from "@/lib/nav";
import { applyScript, type PickedScript } from "@/lib/ofMirrorChat";
import { OF_INSIGHTS_ATTR } from "@/lib/ofMirrorChrome";
import { chatPath, mirrorQuery } from "@/lib/ofMirrorData";
import { ofMeQuery } from "@/lib/ofMirrorIdentity";
import { relay, type AccountMeta, type OFChatItem } from "@/lib/relay";
import { subscribeToStorage } from "@/lib/storageSync";
import { cn } from "@/lib/utils";

/** The routes with the creator column (OF Manager), where it is the creator switch from lg up. */
export function hasCreatorColumn(pathname: string): boolean {
  return pathname === "/of-manager" || pathname.startsWith("/of-manager/");
}

/** Infloww's --tc-* slots this chrome uses, dark then light (REA §3 A). Dark reads the app's theme tokens
 *  (globals.css carries the same Infloww values); light keeps Infloww's own light values, which the app's
 *  light tokens do not match, except the selected row and the blue, which follow the tokens in both. */
const PALETTE = `
.ofm{--ofm-nav:var(--color-bg);--ofm-col:var(--color-bg-elev-1);--ofm-line:var(--color-border);--ofm-fg:var(--color-fg);--ofm-fg2:rgb(255 255 255/62%);--ofm-input:#2f2f2f;--ofm-input-line:#404040;--ofm-placeholder:#949494;--ofm-hover:var(--color-bg-elev-2);--ofm-active:var(--color-selected);--ofm-blue:var(--color-link)}
html[data-theme="light"] .ofm{--ofm-nav:#fff;--ofm-col:#f5f5f5;--ofm-line:#e6e6e6;--ofm-fg:#151515;--ofm-fg2:#666;--ofm-input:#fff;--ofm-input-line:#d9d9d9;--ofm-placeholder:#999;--ofm-hover:#ebebeb}
`;

/** "UTC+02:00": this computer's offset (Infloww's OF Manager shows the local zone, not the Agency's). */
function localOffsetLabel(): string {
  const mins = -new Date().getTimezoneOffset();
  const abs = Math.abs(mins);
  return `UTC${mins < 0 ? "-" : "+"}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
}
const noSubscribe = () => () => {};

/** OF Manager's creator column collapsed to 70px (Infloww's `modelListExpandStatus`), kept across loads. */
const COLLAPSED_KEY = "chatterly:ofm:column-collapsed";
const COLLAPSED_EVENT = "chatterly-ofm-column-collapsed";
const subscribeCollapsed = subscribeToStorage(COLLAPSED_EVENT);
const readCollapsed = () => localStorage.getItem(COLLAPSED_KEY) === "1";
function setCollapsed(on: boolean) {
  if (on) localStorage.setItem(COLLAPSED_KEY, "1");
  else localStorage.removeItem(COLLAPSED_KEY);
  window.dispatchEvent(new Event(COLLAPSED_EVENT));
}

/** Search filters this long after the last keystroke. Infloww waits 800ms, but its search is a server query; ours
 *  filters the loaded list, so a short wait only spares the rows' remounts while typing. */
const SEARCH_WAIT_MS = 300;

/** A creator the OF view can show: a captured session not flagged dead. Every column lists `useActiveAccounts()`
 *  (captured sessions only), so a row that fails this is a logged-out one. */
const liveSession = (a: AccountMeta) => !!a.has_session && !a.session_dead_at;
/** AccountsTable's word for a flagged session. */
const LOGGED_OUT = "Disconnected";

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

/** Share for Share's marks on a creator row: the "S4S" tag (opted in) and its pending received requests. */
export type S4SMark = { optedIn: boolean; pending: number };

/** The 192px creator column; exported for Profile promotion and Smart lists, which list creators the same way. OF
 *  Manager's picks the scope (ScopeContext); with `onChange` the column is controlled instead (`value` is the picked
 *  creator, no "All creators" pick) and carries its own palette, for pages outside the OF Manager chrome. `className`
 *  sizes it. `variant="s4s"` is Share for Share's rail (`pageScene:"s4s"`): 300px, no "All creators" row, 30px
 *  avatars with the S4S tag and the request count from `marks` in place of the online dot and the OF count.
 *  Every copy filters 300ms after typing stops, ↑/↓ walk its rows and Enter picks one; a logged-out row says so and
 *  reads no OF count. OF Manager's own (`ofManager`) also collapses to Infloww's 70px avatar strip (kept across loads),
 *  warms a creator's `/users/me` on hover or focus, and focuses Search on `/` (Infloww has no keys). */
export function CreatorColumn(props: {
  accounts: AccountMeta[];
  onPicked?: () => void;
  value?: string | null;
  onChange?: (accountId: string) => void;
  className?: string;
  variant?: "s4s";
  marks?: Record<string, S4SMark>;
}) {
  return props.onChange ? <ColumnBody {...props} onChange={props.onChange} /> : <ScopedColumn {...props} />;
}

function ScopedColumn({ accounts, onPicked, className }: { accounts: AccountMeta[]; onPicked?: () => void; className?: string }) {
  const { scope, setScope } = useScope();
  const profiles = useCreatorProfiles();
  const [picked, setPicked] = useState("");
  // A Tag renamed or deleted in the Tag manager leaves no group picked.
  const group = profiles.tags.includes(picked) ? picked : "";
  return (
    <ColumnBody
      accounts={group ? accounts.filter((a) => profiles.profiles[a.id]?.tag === group) : accounts}
      className={className}
      value={scope.kind === "model" ? scope.accountId : null}
      onChange={(id) => { setScope({ kind: "model", accountId: id }); onPicked?.(); }}
      all={{ on: !group && scope.kind === "all", pick: () => { setPicked(""); setScope({ kind: "all" }); onPicked?.(); } }}
      groups={{ tags: profiles.tags, value: group, pick: setPicked }}
      ofManager
    />
  );
}

function ColumnBody({ accounts, value, onChange, all, groups, ofManager = false, className, variant, marks }: {
  accounts: AccountMeta[];
  value?: string | null;
  onChange: (accountId: string) => void;
  /** OF Manager's "All creators" pick; without it the menu only closes. */
  all?: { on: boolean; pick: () => void };
  /** OF Manager's creator groups (the Tags) under All creators; `value` "" is none picked. */
  groups?: { tags: string[]; value: string; pick: (tag: string) => void };
  /** OF Manager's own column: it collapses, warms the hovered creator's OF view and owns the `/` key. */
  ofManager?: boolean;
  className?: string;
  variant?: "s4s";
  marks?: Record<string, S4SMark>;
}) {
  const s4s = variant === "s4s";
  // Chats with unread messages per creator, from the badge counts Messages Pro's Creator tabs read (one query for every row).
  const rosterCounts = useRosterCounts();
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setFilter(query), SEARCH_WAIT_MS);
    return () => clearTimeout(t);
  }, [query]);
  const collapsed = useSyncExternalStore(subscribeCollapsed, readCollapsed, () => false) && ofManager;
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const asideRef = useRef<HTMLElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  // Set by an expand for Search: focus it once the input is back.
  const focusSearch = useRef(false);
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: PointerEvent) => { if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false); };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [menuOpen]);
  useEffect(() => {
    if (collapsed || !focusSearch.current) return;
    focusSearch.current = false;
    searchRef.current?.focus();
  }, [collapsed]);
  // `/` focuses Search while nothing has focus: not from a field or an open dialog, nor while the column is hidden
  // below lg.
  useEffect(() => {
    if (!ofManager) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented || e.target !== document.body) return;
      if (asideRef.current?.checkVisibility?.() === false) return;
      e.preventDefault();
      if (readCollapsed()) { focusSearch.current = true; setCollapsed(false); }
      else searchRef.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [ofManager]);
  // ↑/↓ walk the rows (↓ from Search enters the list, ↑ from the first row returns); Enter is the row button's own.
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    if (e.target === searchRef.current && e.key === "ArrowUp") return;
    const rows = Array.from(listRef.current?.querySelectorAll<HTMLElement>('[data-testid="of-creator-row"]') ?? []);
    const i = rows.indexOf(document.activeElement as HTMLElement);
    const next = e.key === "ArrowDown" ? Math.min(i + 1, rows.length - 1) : i - 1;
    e.preventDefault();
    if (next >= 0) rows[next]?.focus();
    else if (i === 0) searchRef.current?.focus();
  };
  const q = filter.trim().toLowerCase();
  const shown = q ? accounts.filter((a) => (a.nickname || a.id).toLowerCase().includes(q)) : accounts;
  // The strip has no Search box, so it never stays filtered.
  const toggleCollapsed = () => {
    if (!collapsed) { setQuery(""); setFilter(""); }
    setCollapsed(!collapsed);
  };
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["accounts"] });
    void qc.invalidateQueries({ queryKey: ["of-notif-count"] });
  };

  return (
    <aside
      ref={asideRef}
      className={cn(
        "ofm hidden lg:flex w-48 shrink-0 h-chat flex-col bg-[var(--ofm-col)] text-[var(--ofm-fg)]",
        s4s && "w-[300px]",
        className,
        collapsed && "w-[70px]",
      )}
      aria-label="Creators"
      data-testid="of-creator-column"
      data-collapsed={collapsed || undefined}
      onKeyDown={onKeyDown}
    >
      {!all && <style>{PALETTE}</style>}
      {collapsed ? (
        <div className="flex justify-center pt-4">
          <button
            type="button"
            onClick={() => { focusSearch.current = true; setCollapsed(false); }}
            title="Search"
            aria-label="Search creators"
            className="w-10 h-10 grid place-items-center rounded border border-[var(--ofm-input-line)] bg-[var(--ofm-input)] text-[var(--ofm-fg2)] hover:text-[var(--ofm-fg)]"
          >
            <Search aria-hidden className="w-4 h-4" />
          </button>
        </div>
      ) : <div className="flex items-center gap-2 px-2.5 pt-4">
        <label className="flex-1 min-w-0 h-10 flex items-center gap-1 px-3 rounded border border-[var(--ofm-input-line)] bg-[var(--ofm-input)]">
          <input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search"
            aria-label="Search creators"
            className="flex-1 min-w-0 bg-transparent outline-none text-sm placeholder:text-[var(--ofm-placeholder)]"
          />
          <Search aria-hidden className="w-4 h-4 shrink-0 text-[var(--ofm-fg2)]" />
        </label>
        <button
          type="button"
          onClick={refresh}
          title="Refresh"
          aria-label="Refresh creators"
          className="w-9 h-[38px] shrink-0 grid place-items-center rounded border border-[var(--ofm-input-line)] bg-[var(--ofm-input)] text-[var(--ofm-fg2)] hover:text-[var(--ofm-fg)]"
        >
          <RotateCw aria-hidden className="w-4 h-4" />
        </button>
      </div>}
      {(s4s || collapsed) && <div className="h-4 shrink-0" />}
      {!s4s && !collapsed && <div className="relative" ref={menuRef}>
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          aria-expanded={menuOpen}
          className="w-full h-16 flex items-center justify-between px-4 text-sm text-[var(--ofm-blue)]"
        >
          <span className="truncate">{groups?.value || "All creators"}</span>
          <ChevronDown aria-hidden className="w-3 h-3 shrink-0 text-[#8c8c8c]" />
        </button>
        {menuOpen && (
          <div className="absolute left-4 right-4 top-14 z-10 max-h-72 overflow-y-auto rounded border border-[var(--ofm-line)] bg-[var(--ofm-col)] shadow-lg py-1">
            <button
              type="button"
              className={cn("w-full text-left px-3 h-9 text-sm hover:bg-[var(--ofm-hover)]", (!all || all.on) && "text-[var(--ofm-blue)]")}
              onClick={() => { setMenuOpen(false); all?.pick(); }}
            >
              All creators
            </button>
            {groups?.tags.map((t) => (
              <button
                key={t}
                type="button"
                className={cn("w-full text-left px-3 h-9 text-sm truncate hover:bg-[var(--ofm-hover)]", groups.value === t && "text-[var(--ofm-blue)]")}
                onClick={() => { setMenuOpen(false); groups.pick(t); }}
              >
                {t}
              </button>
            ))}
          </div>
        )}
      </div>}
      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto">
        {shown.length === 0 ? (
          <EmptyState kind="data" className="mt-24" textClassName="text-base text-[#8f8f8f]" />
        ) : (
          shown.map((a) => s4s ? (
            <S4SRow key={a.id} account={a} active={value === a.id} mark={marks?.[a.id]} onPick={() => onChange(a.id)} />
          ) : (
            <CreatorRow
              key={a.id}
              account={a}
              active={value === a.id}
              unread={rosterCounts[a.id]?.unread ?? 0}
              onPick={() => onChange(a.id)}
              collapsed={collapsed}
              prefetch={ofManager}
            />
          ))
        )}
      </div>
      {ofManager && (
        <button
          type="button"
          onClick={toggleCollapsed}
          title={collapsed ? "Expand" : "Collapse"}
          aria-label={collapsed ? "Expand creators" : "Collapse creators"}
          aria-expanded={!collapsed}
          className={cn(
            "h-10 shrink-0 flex items-center border-t border-[var(--ofm-line)] text-[var(--ofm-fg2)] hover:text-[var(--ofm-fg)]",
            collapsed ? "justify-center" : "justify-end px-4",
          )}
        >
          {collapsed ? <ChevronsRight aria-hidden className="w-4 h-4" /> : <ChevronsLeft aria-hidden className="w-4 h-4" />}
        </button>
      )}
    </aside>
  );
}

function CreatorRow({ account, active, unread, onPick, collapsed = false, prefetch = false }: {
  account: AccountMeta;
  active: boolean;
  /** Chats with unread messages (the roster counts). */
  unread: number;
  onPick: () => void;
  /** The 70px strip: the avatar and its dot only. */
  collapsed?: boolean;
  /** Warm the creator's `/users/me` (the mirror's first read for any page) on hover or focus, so a switch paints at once. */
  prefetch?: boolean;
}) {
  const name = account.nickname || account.id;
  const online = liveSession(account);
  const qc = useQueryClient();
  // The OnlyFans notification count; same query as Messages Pro's bell, so the two share it. Fresh for 60s, as
  // Infloww's; a creator without a live session has none to read (Infloww shows the chip for linked ones only).
  const countQ = useQuery<number>({
    queryKey: ["of-notif-count", account.id],
    queryFn: account.id && online
      ? async () => Number((await relay.get<{ all?: number }>("/api/of/v2/users/notifications/count", { accountId: account.id }))?.all) || 0
      : skipToken,
    staleTime: 60_000,
    retry: false,
  });
  const count = !online || countQ.isError ? 0 : countQ.data ?? 0;
  // Hover or focus has to rest 150ms, so a sweep of the mouse or the arrows does not read every creator on the way.
  const dwell = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(dwell.current), []);
  const warm = prefetch && online && !active
    ? () => { clearTimeout(dwell.current); dwell.current = setTimeout(() => void qc.prefetchQuery(ofMeQuery(account.id)), 150); }
    : undefined;
  const cool = () => clearTimeout(dwell.current);
  return (
    <button
      type="button"
      onClick={onPick}
      onMouseEnter={warm}
      onMouseLeave={cool}
      onFocus={warm}
      onBlur={cool}
      aria-current={active || undefined}
      title={online ? name : `${name} · ${LOGGED_OUT}`}
      data-testid="of-creator-row"
      className={cn(
        "w-full flex items-center gap-3 px-4 py-3 text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--ofm-blue)]",
        collapsed && "justify-center px-0",
        active ? "bg-[var(--ofm-active)]" : "hover:bg-[var(--ofm-hover)]",
      )}
    >
      <span className="relative w-9 h-9 shrink-0">
        <span className="block w-9 h-9 rounded overflow-hidden">
          <AccountAvatarPicture account={account} letters={1} initialClassName="text-sm font-semibold" />
        </span>
        <span
          aria-label={online ? "Online" : LOGGED_OUT}
          className={cn("absolute -right-1 -bottom-1 w-3 h-3 rounded-full border-2 border-[var(--ofm-col)]", online ? "bg-[#59a744]" : "bg-[#8c8c8c]")}
        />
      </span>
      {!collapsed && <span className="min-w-0 flex flex-col gap-1">
        <span className="text-sm font-medium truncate">{name}</span>
        {!online && <span className="text-xs text-err truncate">{LOGGED_OUT}</span>}
        {(count > 0 || unread > 0) && (
          <span className="self-start flex items-center gap-1">
            {count > 0 && (
              <span className="flex items-center gap-0.5 px-1 py-px rounded bg-[#FFC49A] text-[#151515] text-[10px] font-medium leading-none tabular-nums">
                <Bell aria-hidden className="w-3 h-3" />
                {count > 99 ? "99+" : count}
              </span>
            )}
            {/* Infloww's message unread chip (ModelItem): #FF7C71, radius 22, white text. */}
            {unread > 0 && (
              <span
                aria-label={`${unread} unread chats`}
                className="px-1 py-px rounded-[22px] bg-[#FF7C71] text-white text-[10px] font-medium leading-none tabular-nums"
              >
                {unread > 99 ? "99+" : unread}
              </span>
            )}
          </span>
        )}
      </span>}
    </button>
  );
}

/** The S4S rail's row (`_1tnj2`): `0 16px`, 13px vertical, a 30px radius-4 avatar with the #18cba1 "S4S" tag over its
 *  foot when the creator is opted in, the 14 / 500 name, and the #2ad4ac count of pending received requests. */
function S4SRow({ account, active, mark, onPick }: {
  account: AccountMeta;
  active: boolean;
  mark?: S4SMark;
  onPick: () => void;
}) {
  const name = account.nickname || account.id;
  const pending = mark?.pending ?? 0;
  return (
    <button
      type="button"
      onClick={onPick}
      aria-current={active || undefined}
      title={name}
      data-testid="of-creator-row"
      className={cn(
        "w-full flex items-center gap-3 px-4 py-[13px] text-left",
        active ? "bg-[var(--ofm-active)]" : "hover:bg-[var(--ofm-hover)]",
      )}
    >
      <span className="relative w-[30px] h-[30px] shrink-0">
        <span className="block w-[30px] h-[30px] rounded overflow-hidden">
          <AccountAvatarPicture account={account} letters={1} initialClassName="text-xs font-semibold" />
        </span>
        {mark?.optedIn && (
          <span className="absolute left-1/2 -bottom-1 -translate-x-1/2 rounded-sm bg-[#18cba1] px-1 text-[8px] font-semibold leading-[12px] text-[#151515]">
            S4S
          </span>
        )}
      </span>
      <span className="min-w-0 flex-1 truncate text-sm font-medium">{name}</span>
      {pending > 0 && (
        <span aria-label={`${pending} new request${pending === 1 ? "" : "s"}`}
          className="shrink-0 rounded-sm bg-[#2ad4ac] px-[7px] py-0.5 text-[8px] font-semibold leading-none text-[#151515] tabular-nums">
          {pending > 99 ? "99+" : pending}
        </span>
      )}
    </button>
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
