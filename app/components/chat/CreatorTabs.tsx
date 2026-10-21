"use client";

/**
 * CreatorTabs — the Window header's Creator tabs strip (the Clone's `.ctabs`,
 * docs/spec/phase-01-window-chrome-tabs.md) and "+ Add a Creator" after it:
 * one named tab per open Creator, in the store's order (`useCreatorTabs`),
 * each with its avatar, its unread total and its ✕. It replaces the roster
 * rail inside Messages Pro.
 *
 * - The unread total is the number of unread conversations from the roster
 *   counts (`useRosterCounts`), which refresh every Creator every 60s and on
 *   realtime events. After it, in teal, the Creator's OnlyFans notification
 *   count (`useOfNotifCount`, the Notifications button's read).
 * - Clicking a tab, or Enter or Space on it, sets the scope to that Creator,
 *   so the Fan List switches. The active tab is `aria-selected`.
 * - The roster's warm-up is kept (`useCreatorWarmUp`): picking a tab, or
 *   hovering or focusing it for 250ms, prefetches that Creator's Fan List and
 *   refreshes its unread count.
 * - ✕ closes a tab (messages.js:352-365). Closing the active tab activates
 *   the first remaining one; focus moves to the active tab, or to "+ Add a
 *   Creator" when none remain, and then the scope is left alone. An empty
 *   strip says why (messages.js:284, :3410).
 * - Dragging a tab onto another moves it to that tab's place, through the
 *   house's HTML5 drag helper (`useReorder`); the dragged tab dims and a
 *   2px drop marker shows where it lands (messages.js:297-333).
 *   ArrowLeft / ArrowRight on a focused tab move it one place and focus
 *   follows it (messages.js:334-348). The order is saved by the store.
 * - "+ Add a Creator" opens the Creator picker (messages.js:368-388): every
 *   session-bearing Creator, "open" or "add". Picking one reopens its tab
 *   and activates it. The picker closes on an outside pointer-down or Escape.
 * - The sort button after it (MP2's chat sorting, 04-messages-pro P9) orders
 *   the strip: Custom order (the saved one), Most unread first, A – Z or
 *   Z – A, saved with the tabs (`useCreatorTabs`'s `sort`). Dragging or
 *   moving a tab while sorted keeps the order shown and makes it the custom one.
 * - Right-clicking a tab offers "Open in a new window" (the Fan List row's
 *   menu, `OpenInNewWindowMenu`): a Pop-out window on that Creator, at the
 *   Creator window URL (`creatorWindowHref`).
 */

import { useLayoutEffect, useRef, type HTMLAttributes, type RefObject } from "react";
import { ArrowUpDown, Plus } from "lucide-react";

import { AccountAvatarPicture } from "@/components/ui/AccountAvatarPicture";
import { useScope } from "@/contexts/ScopeContext";
import { useCreatorWarmUp } from "@/hooks/useCreatorWarmUp";
import { useOfNotifCount } from "@/hooks/useOfNotifCount";
import { useReorder } from "@/hooks/useReorder";
import { useRosterCounts } from "@/hooks/useRosterCounts";
import { MP } from "@/lib/messagesPro";
import type { AccountMeta } from "@/lib/relay";
import { cn } from "@/lib/utils";
import { MENU, MENU_ITEM } from "./MenuParts";
import { OpenInNewWindowMenu } from "./OpenInNewWindowMenu";
import { NotifMiniBadge, UnreadMiniBadge } from "./UnreadMiniBadge";
import { sortTabs, useCreatorTabs, type CreatorSort, type CreatorTabsStore } from "./useCreatorTabs";
import { useFanListMenu } from "./useFanListMenu";

const G = MP.creatorTabs;
const O = MP.ours.CreatorTabs;
/** The drop marker on the side the dragged tab will land. */
const DROP_MARK = { before: O.dropMarkBefore, after: O.dropMarkAfter } as const;

/** The Creator window URL (spec, Contracts): a Pop-out window of Messages
 *  Pro on that Creator, which the `account` parameter scopes to. */
function creatorWindowHref(accountId: string): string {
  return `/messages-pro?account=${encodeURIComponent(accountId)}`;
}

/** Where focus goes once the strip has re-rendered: a Creator's tab, or
 *  "+ Add a Creator". */
type FocusTarget = { tab: string } | "add" | null;

export function CreatorTabs() {
  const store = useCreatorTabs();
  const { ready, close, reopen, reorder, sort, setSort } = store;
  const counts = useRosterCounts();
  // The strip's order: the store's, in the chosen sort.
  const open = sortTabs(store.open, sort, (id) => counts[id]?.unread ?? 0);
  const { scope, setScope } = useScope();
  const { warm, hoverThen, clearHover } = useCreatorWarmUp();
  const activeId = scope.kind === "model" ? scope.accountId : null;

  const tabRefs = useRef(new Map<string, HTMLButtonElement>());
  const addRef = useRef<HTMLButtonElement | null>(null);
  const focusNext = useRef<FocusTarget>(null);
  useLayoutEffect(() => {
    const target = focusNext.current;
    if (!target) return;
    focusNext.current = null;
    (target === "add" ? addRef.current : tabRefs.current.get(target.tab))?.focus();
  });

  const pick = (accountId: string) => {
    clearHover();
    setScope({ kind: "model", accountId });
    warm(accountId);
  };

  const closeTab = (accountId: string) => {
    const left = open.filter((a) => a.id !== accountId);
    close(accountId);
    if (left.length === 0) {
      focusNext.current = "add";
      return;
    }
    const stillActive = left.find((a) => a.id === activeId);
    const next = stillActive ?? left[0];
    if (accountId === activeId) pick(next.id);
    focusNext.current = { tab: next.id };
  };

  // Focus stays on a moved tab: the tabs are keyed by Creator, so React
  // moves the focused node and restores its focus after the commit.
  const drag = useReorder(open, (next) => reorder(next.map((a) => a.id)), (a) => a.id);

  const reopenTab = (accountId: string) => {
    reopen(accountId);
    pick(accountId);
    focusNext.current = { tab: accountId };
  };

  return (
    <>
      <div role="tablist" aria-label="Creator tabs" className={cn(G.strip, "flex items-end min-w-0 overflow-x-auto no-scrollbar")}>
        {open.map((a, idx) => {
          const counted = counts[a.id];
          const from = drag.draggingIndex;
          // The marker shows on the tab dragged over, on the side the dragged
          // tab lands: `useReorder` puts it in that tab's place.
          const dropMark = from === null || from === idx || drag.dragOverIndex !== idx
            ? null
            : idx < from ? "before" : "after";
          return (
            <CreatorTab
              key={a.id}
              account={a}
              unread={counted ? counted.unread : 0}
              active={a.id === activeId}
              dragging={from === idx}
              dropMark={dropMark}
              dragProps={{
                draggable: true,
                onDragStart: (e) => drag.onDragStart(e, idx),
                onDragOver: (e) => drag.onDragOver(e, idx),
                onDrop: (e) => drag.onDrop(e, idx),
                onDragEnd: drag.onDragEnd,
              }}
              onMove={(dir) => drag.onKeyboardMove(idx, dir)}
              tabRef={(el) => {
                if (el) tabRefs.current.set(a.id, el);
                else tabRefs.current.delete(a.id);
              }}
              onPick={() => pick(a.id)}
              onClose={() => closeTab(a.id)}
              onHover={() => hoverThen(() => warm(a.id))}
              onHoverEnd={clearHover}
            />
          );
        })}
      </div>
      {/* After the tablist, not in it (a tablist owns tabs only); the empty
       *  strip has no width, so it sits where the Clone's does. */}
      {ready && open.length === 0 && (
        <span className={cn(G.empty, "whitespace-nowrap text-fg-dim")}>
          {store.closed.length > 0
            ? "All creator tabs closed — use “+ Add a Creator”"
            : "No creators on this relay"}
        </span>
      )}
      <AddCreator open={open} closed={store.closed} addRef={addRef} onPick={reopenTab} />
      <SortTabs sort={sort} onSort={setSort} />
    </>
  );
}

function CreatorTab({
  account, unread, active, dragging, dropMark, dragProps, onMove, tabRef, onPick, onClose, onHover, onHoverEnd,
}: {
  account: AccountMeta;
  unread: number;
  active: boolean;
  dragging: boolean;
  /** The drop marker's side, while another tab is dragged over this one. */
  dropMark: keyof typeof DROP_MARK | null;
  dragProps: Pick<HTMLAttributes<HTMLDivElement>,
    "draggable" | "onDragStart" | "onDragOver" | "onDrop" | "onDragEnd">;
  /** Move this tab one place left (-1) or right (1). */
  onMove: (dir: -1 | 1) => void;
  tabRef: (el: HTMLButtonElement | null) => void;
  onPick: () => void;
  onClose: () => void;
  onHover: () => void;
  onHoverEnd: () => void;
}) {
  const name = account.nickname || account.id;
  // Infloww's second badge: the Creator's OnlyFans notification count, the
  // same read (and cache entry) as the Notifications button.
  const { count: notifs } = useOfNotifCount(account.id);
  return (
    <OpenInNewWindowMenu href={creatorWindowHref(account.id)}>
      <div
        {...dragProps}
        className={cn(
          G.tab,
          "flex flex-none items-center",
          active
            ? "bg-accent/15 border-accent/55 text-fg"
            : "bg-[var(--inf-tab,var(--color-panel))] border-transparent text-fg hover:bg-bg-elev-1",
          (active || dropMark) && "inset-shadow-accent",
          dropMark ? DROP_MARK[dropMark] : active && G.tabActive,
          dragging && "opacity-40",
        )}
      >
        <button
          ref={tabRef}
          type="button"
          role="tab"
          aria-selected={active}
          onClick={onPick}
          onKeyDown={(e) => {
            if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
            e.preventDefault();
            onMove(e.key === "ArrowLeft" ? -1 : 1);
          }}
          onMouseEnter={onHover}
          onMouseLeave={onHoverEnd}
          onFocus={onHover}
          onBlur={onHoverEnd}
          // The Clone's tooltip (messages.js:268-269): the whole name, which the
          // tab may cut short, and the unread total.
          title={`${name} — ${unread} unread`}
          className={cn(O.tabPick, "flex min-w-0 h-full items-center")}
        >
          <span aria-hidden className={cn(G.avatar, "overflow-hidden flex-none")}>
            <AccountAvatarPicture account={account} letters={2} initialClassName="" />
          </span>
          <span className={cn(G.name, "min-w-0 truncate")}>{name}</span>
          {unread > 0 && <UnreadMiniBadge count={unread} />}
          {notifs > 0 && <NotifMiniBadge count={notifs} />}
        </button>
        {/* The ✕ is the tab's sibling inside the tablist, not inside the tab:
         *  a button cannot nest in a button, and inside the tab it would join
         *  the tab's accessible name. */}
        <button
          type="button"
          onClick={onClose}
          aria-label={`Close ${name}`}
          // The Clone's tooltip (messages.js:278).
          title="Close this tab (reopen from + Add a Creator)"
          className={cn(G.close, "flex-none grid place-items-center text-fg-dim hover:text-fg")}
        >
          <span aria-hidden>✕</span>
        </button>
      </div>
    </OpenInNewWindowMenu>
  );
}

/** "+ Add a Creator" and its Creator picker: the open tabs in strip order,
 *  then the closed ones. */
function AddCreator({
  open, closed, addRef, onPick,
}: {
  open: AccountMeta[];
  closed: CreatorTabsStore["closed"];
  addRef: RefObject<HTMLButtonElement | null>;
  onPick: (accountId: string) => void;
}) {
  const { open: menuOpen, setOpen, ref, triggerProps, menuProps } = useFanListMenu<HTMLDivElement>();
  const rows = [
    ...open.map((account) => ({ account, meta: "open" })),
    ...closed.map((account) => ({ account, meta: "add" })),
  ];
  return (
    <div ref={ref} className="relative self-center flex-none">
      <button ref={addRef} type="button" {...triggerProps} className={cn(MP.windowHeader.addCreator, "flex items-center whitespace-nowrap text-fg")}>
        <Plus aria-hidden className={MP.windowHeader.addCreatorIcon} />
        Add a Creator
      </button>
      {menuOpen && (
        <section
          {...menuProps}
          aria-label="Creator picker"
          className={cn(MENU, O.pickerPlace)}
        >
          {/* The Clone's heading (messages.js:380). */}
          <div className={cn(MP.menu.head, "uppercase text-fg-dim")}>Creators on this relay ({rows.length})</div>
          {rows.map(({ account, meta }) => (
            <button
              key={account.id}
              type="button"
              onClick={() => { setOpen(false); onPick(account.id); }}
              className={MENU_ITEM}
            >
              <span aria-hidden className={cn(MP.menu.avatar, "overflow-hidden flex-none")}>
                <AccountAvatarPicture account={account} letters={2} initialClassName="" />
              </span>
              <span className="min-w-0 truncate">{account.nickname || account.id}</span>
              {/* A space for the accessible name ("Name add"); see the tab's. */}
              {" "}
              <span className={cn(MP.menu.meta, "ml-auto flex-none text-fg-dim")}>{meta}</span>
            </button>
          ))}
        </section>
      )}
    </div>
  );
}

const SORT_LABEL: Record<CreatorSort, string> = {
  custom: "Custom order",
  unread: "Most unread first",
  az: "A – Z",
  za: "Z – A",
};

/** The strip's sort button and its menu; the chosen order is checked. */
function SortTabs({ sort, onSort }: { sort: CreatorSort; onSort: (sort: CreatorSort) => void }) {
  const { open, setOpen, ref, triggerProps, menuProps } = useFanListMenu<HTMLDivElement>();
  return (
    <div ref={ref} className="relative self-center flex-none">
      <button
        type="button"
        {...triggerProps}
        aria-label="Sort creator tabs"
        title={`Sort creator tabs: ${SORT_LABEL[sort]}`}
        className={cn(MP.windowHeader.addCreator, "flex items-center text-fg-dim hover:text-fg")}
      >
        <ArrowUpDown aria-hidden className={MP.windowHeader.addCreatorIcon} />
      </button>
      {open && (
        <section {...menuProps} aria-label="Sort creator tabs" className={cn(MENU, O.pickerPlace)}>
          {(Object.keys(SORT_LABEL) as CreatorSort[]).map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={sort === key}
              onClick={() => { setOpen(false); onSort(key); }}
              className={MENU_ITEM}
            >
              <span aria-hidden className="w-4 text-center">{sort === key ? "✓" : ""}</span>
              <span>{SORT_LABEL[key]}</span>
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
