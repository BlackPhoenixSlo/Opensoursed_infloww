"use client";

/**
 * OF Manager's creator column (CreatorColumn) and the palette it carries.
 * Its own module, apart from OfManagerChrome: CreatorRail and the pages that list creators the same way import it,
 * and OfManagerChrome's Fan insights (FanDrawer, the Scripts picker, the OF mirror's chat and data modules) must not
 * ride along into theirs. Its route test (hasCreatorColumn) is in lib/nav, so the app shell imports nothing from here.
 * OF Manager's "All creators" select is Infloww's GroupSelect: All creators, then each Tag (a Tag is Infloww's creator
 * group, useCreatorProfiles), which narrows the rows to the creators holding it. A chatter is refused the Tags' blob,
 * so it offers All creators alone.
 */

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { skipToken, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, ChevronDown, ChevronsLeft, ChevronsRight, RotateCw, Search } from "lucide-react";

import { AccountAvatarPicture } from "@/components/ui/AccountAvatarPicture";
import { EmptyState } from "@/components/ui/infloww";
import { useScope } from "@/contexts/ScopeContext";
import { useCreatorProfiles } from "@/lib/creatorProfiles";
import { useRosterCounts } from "@/hooks/useRosterCounts";
import { ofMeQuery } from "@/lib/ofMe";
import { relay, type AccountMeta } from "@/lib/relay";
import { subscribeToStorage } from "@/lib/storageSync";
import { cn } from "@/lib/utils";

/** Infloww's --tc-* slots this chrome uses, dark then light (REA §3 A). Dark reads the app's theme tokens
 *  (globals.css carries the same Infloww values); light keeps Infloww's own light values, which the app's
 *  light tokens do not match, except the selected row and the blue, which follow the tokens in both. */
export const PALETTE = `
.ofm{--ofm-nav:var(--color-bg);--ofm-col:var(--color-bg-elev-1);--ofm-line:var(--color-border);--ofm-fg:var(--color-fg);--ofm-fg2:rgb(255 255 255/62%);--ofm-input:#2f2f2f;--ofm-input-line:#404040;--ofm-placeholder:#949494;--ofm-hover:var(--color-bg-elev-2);--ofm-active:var(--color-selected);--ofm-blue:var(--color-link)}
html[data-theme="light"] .ofm{--ofm-nav:#fff;--ofm-col:#f5f5f5;--ofm-line:#e6e6e6;--ofm-fg:#151515;--ofm-fg2:#666;--ofm-input:#fff;--ofm-input-line:#d9d9d9;--ofm-placeholder:#999;--ofm-hover:#ebebeb}
`;

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
export const liveSession = (a: AccountMeta) => !!a.has_session && !a.session_dead_at;
/** AccountsTable's word for a flagged session. */
const LOGGED_OUT = "Disconnected";

/** Share for Share's marks on a creator row: the "S4S" tag (opted in) and its pending received requests. */
export type S4SMark = { optedIn: boolean; pending: number };

/** The 192px creator column; exported for Profile promotion and Smart lists, which list creators the same way. OF
 *  Manager's picks the scope (ScopeContext); with `onChange` the column is controlled instead (`value` is the picked
 *  creator; `all` adds the "All creators" pick, else that menu only closes) and carries its own palette, for pages
 *  outside the OF Manager chrome (`CreatorRail` lays it out beside a page's content). `className`
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
  /** A controlled column's "All creators" pick; `on` while it is the pick. */
  all?: { on: boolean; pick: () => void };
  /** A controlled column with no "All creators" row at all (pages that always work on one creator). */
  noAll?: boolean;
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

function ColumnBody({ accounts, value, onChange, all, noAll = false, groups, ofManager = false, className, variant, marks }: {
  accounts: AccountMeta[];
  value?: string | null;
  onChange: (accountId: string) => void;
  /** The "All creators" pick (OF Manager's, or a controlled column's); without it the menu only closes. */
  all?: { on: boolean; pick: () => void };
  /** No "All creators" row. */
  noAll?: boolean;
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
      {!ofManager && <style>{PALETTE}</style>}
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
      {(s4s || collapsed || noAll) && <div className="h-4 shrink-0" />}
      {!s4s && !collapsed && !noAll && <div className="relative" ref={menuRef}>
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
